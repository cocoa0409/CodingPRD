# Personal Chef & In-Home Dining API — Product Requirements Document

## 1. Introduction

Hiring a personal chef for an in-home dinner is, underneath the hospitality, a logistics and money problem. A client picks a chef, a menu, a party size, and a date; the chef has to be free that evening, has to physically reach the address, has to bring the right equipment, and has to charge a price that reflects both their labor and the actual cost of the groceries they buy. None of those facts are known with certainty up front — ingredient prices float, dates slip, parties shrink, and bookings get cancelled at the last minute — so the platform's job is to hold a consistent, auditable picture of every booking as it moves from a hopeful request to a completed, fully-paid event.

This API backs that platform. It coordinates **chefs** (who publish menus, declare travel zones and unavailable windows, and confirm or decline the bookings made against them), **clients** (who request bookings, pay a deposit and later a balance, and may cancel, reschedule, or set up a recurring meal-prep plan), and a **platform administrator** who handles operational chores such as suspending a misbehaving chef and pinning the test clock. The financial core is a quote engine: chef labor with a small-party surcharge, ingredient costs marked up on a volume-tiered schedule, and a flat travel fee per zone, reconciled twice — once provisionally from estimates at confirmation, then again from real grocery receipts before the balance is billed.

The design emphasizes that derived numbers are never stored stale. Every quote total, balance, chef reliability score, and capacity counter is recomputed inside the same request that changes its inputs, and the more dangerous mutations — cancellations and plan pauses — cascade through grocery runs, payments, availability holds, and chef-level aggregates in a single atomic step. This document specifies those rules precisely so that two independent implementations would compute the same cents, hold the same calendar slots, and reject the same bad requests.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401) before any other processing. If the role value is not one of the three roles defined below, or the role is recognized but not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

There are exactly three roles, spelled precisely as follows: `Chef`, `Client`, and `PlatformAdmin`.

- A `Chef` is the service provider. It owns its catalog — its menu packages, its travel zones, and its declared availability blocks — and it owns the bookings made against it. A chef confirms, declines, starts prep on, and completes its own bookings, opens and finalizes grocery runs, and accepts or rejects reschedule proposals on its bookings. When `X-User-Role` is `Chef`, `X-User-ID` is the `id` of the acting `Chef`; ownership checks on any resource that references a chef compare the resource's `chef_id` to `X-User-ID`. For a `GroceryRun` or a `RescheduleRequest`, which reference a booking rather than a chef directly, the ownership check resolves to the `chef_id` of the parent booking.
- A `Client` is the customer. It registers itself, books chefs, pays deposits and balances, cancels and withdraws reschedule proposals on its own bookings, and owns recurring meal-prep plans. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a client compare the resource's `client_id` to `X-User-ID` (for a booking-scoped client action such as cancellation, the comparison is against the parent booking's `client_id`; for a plan, against the plan's `client_id`).
- A `PlatformAdmin` is an operational role: it suspends and re-activates chefs, may register chefs and clients, and controls the test clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; a `PlatformAdmin` is never subject to the `chef_id`/`client_id` ownership check.

When an authenticated, role-permitted caller is nonetheless not the owner of the specific resource being mutated, the rejection is `ERR_NOT_RESOURCE_OWNER` (HTTP 403). Ownership is distinct from role: a `Chef` may hold the `Chef` role yet still be rejected for acting on another chef's booking.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

All list (collection) endpoints are paginated through two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. A request supplying a `limit` outside the inclusive range of 1 to 100 is treated as a malformed request.

List results are returned in ascending order of `created_at` — the oldest matching record first — unless an endpoint's narrative states otherwise. The `meta` block of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the filter before pagination is applied and `has_more` is true when records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` that is a UUID with no type prefix. Every resource also carries a `created_at` timestamp, recorded as an ISO 8601 UTC instant with three fractional digits, set once at creation and never altered.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `version` begins at 1 when the resource is created and increases by exactly 1 on every mutation that changes the resource's persisted state; `updated_at` is refreshed to the time of that mutation. The entities that carry the full set — `id`, `created_at`, `updated_at`, and `version` — are `Chef`, `MenuPackage`, `TravelZone`, `AvailabilityBlock`, `Client`, `Booking`, `GroceryRun`, `Payment`, `RecurringPlan`, and `RescheduleRequest`. In this domain every entity carries the full common-field set; there is no entity that omits `updated_at` and `version`.

When an operation recomputes a derived field on a resource (for example, a chef's reliability score or a booking's balance), that recomputation is a mutation: it bumps the affected resource's `version` and refreshes its `updated_at`.

### 2.5. Optimistic Concurrency on Chef Confirmation

Confirming a booking is the one write in this system that takes an explicit version guard. A request to confirm a booking must include `expected_chef_version`, carrying the value of the chef's `version` that the client last observed. This field is mandatory on the confirm operation; it is not accepted on, and not required by, any other endpoint.

Before any business validation runs, the server compares `expected_chef_version` against the booked chef's current `version`. If they do not match — because some other write has advanced the chef's `version` since the client last read it — the confirmation is rejected with `ERR_STALE_VERSION` (HTTP 412). Each successful confirmation mints an availability hold and bumps the chef's occupancy, which itself advances `Chef.version`; the guard therefore ensures that a slot legitimately taken by an earlier confirmation cannot be overwritten by a confirmation working from an outdated view of the chef's calendar. The version check precedes ownership, state, allergen, equipment, time, and capacity checks on the confirm path.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and exchanged as integer cents; there are no fractional cents in any persisted field or response. Wherever a calculation produces a non-integer cents value — a surcharge multiplication, a markup multiplication, a percentage of a quote, or a fraction of a payment — the result is rounded **half up** (a value exactly at the half-cent rounds to the next whole cent away from zero) to a whole number of cents. The exact point at which rounding is applied differs between calculations and is specified with each calculation in §3; this matters because rounding once over a sum can differ from rounding each addend and then summing, and the system pins which of the two it uses in each case. Rates such as the grocery markup and the cancellation refund fraction are exact decimal values, not rounded.

### 2.7. Calendar Occupancy and Half-Open Intervals

A chef's calendar is modeled as a set of `AvailabilityBlock` intervals. Each block occupies the half-open interval from its `window_start_utc` (inclusive) to its `window_end_utc` (exclusive). Two intervals overlap when one starts strictly before the other ends and ends strictly after the other starts; because the intervals are half-open, a block that ends exactly when another begins does **not** overlap it — back-to-back events are permitted. A block's `status` is either `HELD`, meaning it currently occupies the calendar, or `RELEASED`, meaning it no longer does. Only `HELD` blocks participate in overlap checks.

Blocks come in two `kind` values. A `BLACKOUT` block is a chef-declared unavailable window — the only kind a chef creates directly, with its `chef_id` supplied in the create body, its `booking_id` null, its `kind` set to `BLACKOUT`, and its `status` set to `HELD`. A `BOOKING_HOLD` block is system-minted when a booking is confirmed; its `booking_id` points to that booking and its `chef_id` is copied from the booking. The occupied window of a booking is widened by the chef's prep time: a `BOOKING_HOLD` runs from the booking's `event_start_utc` minus the chef's `prep_buffer_minutes` up to the booking's `event_end_utc`.

### 2.8. Nested Lookups and Filtered Retrieval

The API is flat: every entity is its own top-level collection, and children reference their parents by foreign-key body fields rather than by nested URL paths. Relationships are discovered through filtered list endpoints — for example, a chef's menus are retrieved by listing menus filtered by `chef_id`, and a booking's payments by listing payments filtered by `booking_id`. When an endpoint addresses a resource by a path identifier, that identifier is validated first; an unknown id yields the appropriate not-found error (`ERR_CHEF_NOT_FOUND`, `ERR_MENU_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_RESCHEDULE_NOT_FOUND`, `ERR_GROCERY_RUN_NOT_FOUND`, and — for the two GET-by-id reads on entities the catalogue above otherwise omits — `ERR_BLOCK_NOT_FOUND` for an unknown `AvailabilityBlock` id on `GET /availability-blocks/{blockId}` and `ERR_PAYMENT_NOT_FOUND` for an unknown `Payment` id on `GET /payments/{paymentId}`, all HTTP 404) before any state or business rule is evaluated. On creates that carry foreign keys in the body (a booking or a recurring plan referencing `chef_id`, `client_id`, and `menu_package_id`), each referenced entity must exist or the create is rejected with the corresponding not-found error.

### 2.9. Validation Ordering

When several checks guard a single operation, they are evaluated in a fixed priority order so that the same bad request always produces the same error. The global order is: (1) authentication context present and well-formed (`ERR_MISSING_AUTH_CONTEXT`); (2) the role is recognized and permitted for the operation (`ERR_UNAUTHORIZED_ROLE`); (3) path resource ids exist, validated left to right (the not-found family); (4) referenced foreign-key bodies exist (the not-found family on create); (5) the acting user owns the resource being mutated (`ERR_NOT_RESOURCE_OWNER`); (6) the target resource is in a legal source state for the requested transition, and — where the endpoint declares `expected_chef_version` — the version guard matches, with the version check evaluated before any later business check (`ERR_INVALID_STATE`, `ERR_STALE_VERSION`, `ERR_BOOKING_NOT_CONFIRMED`, `ERR_GROCERY_RUN_NOT_FINALIZED`). One refinement applies to steps (5) and (6): on a plain state-transition endpoint — booking decline, cancel, start-prep, and complete; grocery-run finalize; reschedule accept, reject, and withdraw; and plan pause, resume, and cancel — the check that the *acted-on resource* is in its own legal source state (6, raised as `ERR_INVALID_STATE`) is evaluated *before* the ownership check (5), so a wrong-state request from a non-owner surfaces the state error first; any further cross-entity state gate the operation layers on top (such as the parent booking being `CONFIRMED`, `ERR_BOOKING_NOT_CONFIRMED`, on finalize and reschedule-accept) still follows ownership in the order that operation's own section describes. The two operations whose own narrative pins an explicit early order — booking confirm (version guard then ownership then state, per §2.5 and §3.3) and plan generate-occurrence (ownership then the `ACTIVE` state gate) — instead check ownership before state in the order their sections describe. Beyond that point, the confirm operation layers further business checks whose relative order is given in §3.3, and general field-shape validation (`ERR_INVALID_REQUEST`, HTTP 400) guards every create and update: required fields present, enum values in range, `event_end_utc` strictly after `event_start_utc`, `max_party_size` at least `min_party_size`, and `weekday` between 0 and 6 inclusive.

### 2.10. Cascades and Conserved Quantities

Two quantities in this system are conserved and must never drift. The first is money at the chef level: a chef's `payout_accrued_cents` always equals its `captured_payments_cents` minus its `refunded_payments_cents`, and any operation that captures or refunds a payment recomputes all three together so the identity holds after every step. The second is calendar capacity: a chef's `active_booking_count` is the number of its bookings currently in a `CONFIRMED` or `IN_PREP` state, incremented when a booking is confirmed and decremented when it leaves those states by completion or cancellation. Because cancellations and plan pauses touch several entities at once — payments, grocery runs, availability holds, and chef aggregates — those effects are applied atomically within the triggering request; partial application is never observable. The specific cascades are detailed in §3.

## 3. Business Logic & Workflows

### 3.1. Chefs: Catalog, Activation, and Suspension

A chef registers by supplying a public `display_name` and a `home_base_zip` (the ZIP the chef dispatches from). The registration body may optionally include an `equipment_inventory` — an array of capability tokens the chef brings, such as `SOUS_VIDE`, `COMMERCIAL_GRILL`, or `BLAST_CHILLER`, defaulting to an empty array — a `prep_buffer_minutes` value (the minutes of on-site prep before guests arrive, which widens the occupied window for overlap checks, defaulting to 90 and never negative), and a `max_bookings_per_day` (the hard cap on confirmed or in-progress bookings sharing a single event calendar date, defaulting to 2 and never below 1). A freshly registered chef starts in `DRAFT` status. All of its computed figures are initialized at creation: `completed_bookings_count`, `captured_payments_cents`, `refunded_payments_cents`, `payout_accrued_cents`, and `active_booking_count` all start at 0, while both reliability scores — `settled_reliability_score` and `projected_reliability_score` — start at 50.

Before a chef can take bookings it must be activated, moving its `status` from `DRAFT` to `ACTIVE`. Activation is allowed only when the chef has published at least one menu — that is, at least one `MenuPackage` belonging to the chef whose `is_listed` is true (otherwise `ERR_NO_LISTED_MENU`) — and has declared at least one travel zone (otherwise `ERR_NO_TRAVEL_ZONE`). A chef in `DRAFT` is the typical activation case and is checked against both conditions. Activation increments the chef's `version`.

A `PlatformAdmin` may move an `ACTIVE` chef to `SUSPENDED`; this carries no preconditions and increments the chef's `version`. Suspension is a forward-looking gate: it blocks new booking confirmations against the chef but does not disturb bookings already `CONFIRMED` or in progress. A `SUSPENDED` chef may be returned to `ACTIVE` by a `PlatformAdmin`; that re-activation requires that the chef still has at least one listed menu (`ERR_NO_LISTED_MENU`) and likewise bumps `version`. Going from `DRAFT` to `ACTIVE` is also available to the chef itself, whereas the `ACTIVE`-to-`SUSPENDED` and `SUSPENDED`-to-`ACTIVE` moves are administrative.

### 3.2. Menus, Travel Zones, and Declared Availability

A chef builds its catalog before activation. Creating a menu package requires the owning `chef_id`, a `title`, a `base_price_per_guest_cents` (the chef's labor/menu price per guest, never negative), and an `estimated_ingredient_per_guest_cents` (the estimated raw ingredient cost per guest before markup, never negative). The body may also set a `min_party_size` (the smallest party the menu may be booked for, inclusive, defaulting to 2 and at least 1), a `max_party_size` (the largest, inclusive, defaulting to 12 and never below `min_party_size`), an `allergen_tags` array naming allergens inherently present in the menu (tokens drawn from `PEANUT`, `TREE_NUT`, `SHELLFISH`, `DAIRY`, `GLUTEN`, `EGG`, and `SOY`, defaulting to empty), and a `required_equipment` array of equipment tokens the kitchen or chef must supply to execute the menu (defaulting to empty). A new menu is unlisted: its `is_listed` flag is false until the chef publishes it, after which `is_listed` becomes true. Only listed menus may be booked.

A travel zone is created with the owning `chef_id`, a `zone_code` (a stable zone label such as `ZONE_A`, which must be unique among that chef's zones — a create that repeats a `zone_code` already used by one of the chef's zones is rejected as a malformed request with `ERR_INVALID_REQUEST`), a `zip_prefixes` array of ZIP prefixes the zone covers, and a flat `travel_fee_cents` charged for any event served in that zone (never negative). A booking's service ZIP is matched against the chef's zones by prefix; it must prefix-match exactly one of the chef's zones.

A chef declares unavailable time by creating a blackout block, supplying its `chef_id`, a `window_start_utc`, and a `window_end_utc`. The system stamps the new block with `kind` `BLACKOUT`, `status` `HELD`, and a null `booking_id`. These declared windows occupy the calendar exactly as system holds do and participate in the same overlap checks. Blocks may be listed and filtered by `chef_id`, by `booking_id`, by `status`, or by `kind`.

### 3.3. Booking Requests and the Confirmation Cascade

A client registers itself by supplying a `full_name` and a unique contact `email` (a registration whose `email` duplicates an existing client's is rejected as a malformed request with `ERR_INVALID_REQUEST`), and may optionally declare an `allergen_restrictions` array — allergens the client must avoid, drawn from the same token set as menus (`PEANUT`, `TREE_NUT`, `SHELLFISH`, `DAIRY`, `GLUTEN`, `EGG`, `SOY`), defaulting to empty — and a `dietary_pattern`, one of `OMNIVORE`, `VEGETARIAN`, `VEGAN`, or `PESCATARIAN`, defaulting to `OMNIVORE`.

A client opens a booking by submitting the target `chef_id`, its own `client_id`, the chosen `menu_package_id`, the `party_size` (the confirmed guest count, at least 1), the `service_zip` (the event location ZIP), and the event window as `event_start_utc` and `event_end_utc` (the guest-facing start and end in UTC, with end strictly after start). At creation the system resolves the `travel_zone_id` by prefix-matching `service_zip` against the booked chef's zones and copies the matched zone's fee into the booking's `travel_fee_cents`; if no zone matches, or more than one would, the create is rejected with `ERR_ZIP_OUTSIDE_SERVICE_AREA`. The system also derives `event_date`, the calendar date (formatted `YYYY-MM-DD` in UTC) taken from `event_start_utc`, which is the key used later for daily capacity. The new booking lands with `lifecycle_status` `REQUESTED` and `payment_status` `UNPAID`; its `recurring_plan_id` is null unless the booking was spawned by a plan. No quote is computed yet — pricing is frozen at confirmation. A booking carries two computed money mirrors, `amount_captured_cents` and `amount_refunded_cents`, both starting at 0, and a `cancellation_refund_rate` field that starts at 0 and is overwritten with the applied refund fraction only when the booking is later cancelled (§3.8).

Confirmation is the chef's decision to take a `REQUESTED` booking, advancing its `lifecycle_status` from `REQUESTED` to `CONFIRMED`. It is the most heavily guarded transition in the system, and its checks run in this order after the global auth/existence checks of §2.9: first the version guard of §2.5 (`ERR_STALE_VERSION`); then ownership — the acting chef must own the booking (`ERR_NOT_RESOURCE_OWNER`); then the cross-entity state gate that the chef must be `ACTIVE` (`ERR_CHEF_NOT_ACTIVE`); then allergen safety — the client's `allergen_restrictions` and the menu's `allergen_tags` must share no common token (`ERR_ALLERGEN_CONFLICT`); then equipment — every token in the menu's `required_equipment` must also appear in the chef's `equipment_inventory`, i.e. the required set is a subset of what the chef carries (`ERR_EQUIPMENT_UNAVAILABLE`); then party-size range — `party_size` must fall within the menu's `min_party_size` and `max_party_size`, inclusive on both ends (`ERR_PARTY_SIZE_OUT_OF_RANGE`); then time conflict — the booking's occupied window, running from `event_start_utc` minus the chef's `prep_buffer_minutes` up to `event_end_utc`, must not overlap any `HELD` availability block of the chef under the half-open semantics of §2.7 (`ERR_CHEF_TIME_CONFLICT`); and finally daily capacity — the count of the chef's bookings in `CONFIRMED` or `IN_PREP` sharing the same `event_date` must be strictly less than the chef's `max_bookings_per_day` (`ERR_DAILY_CAPACITY_EXCEEDED`). Allergen safety is deliberately placed ahead of every temporal and fiscal check so a dangerous menu match surfaces first.

When all checks pass, confirmation freezes the quote and reserves the calendar in one atomic step. The grocery markup rate is selected and frozen into `locked_markup_rate` (see §3.4). The chef's labor subtotal is computed into `labor_total_cents`, the estimated grocery total into `estimated_grocery_total_cents`, and the zone fee is carried in `travel_fee_cents`; these combine into `quote_total_cents`, and `deposit_due_cents` is frozen from that quote (all in §3.4). The booking's `balance_due_cents` is set to `quote_total_cents` minus `amount_captured_cents`. A `BOOKING_HOLD` availability block is minted with `status` `HELD` over the buffer-widened window. The chef's `active_booking_count` is incremented and its `projected_reliability_score` is recomputed (see §3.7). Finally the chef's `version` is incremented by 1, which is what makes a subsequent stale-version confirmation detectable.

A chef may instead decline a `REQUESTED` booking, provided it owns the booking (`ERR_NOT_RESOURCE_OWNER`). Declining moves `lifecycle_status` to `DECLINED`, a terminal state. Because no hold is ever minted before confirmation, a decline releases nothing — but a decline does count against the chef's reliability, as §3.7 describes.

### 3.4. Pricing: Labor, Tiered Grocery Markup, Travel, Deposit

Four figures make up a quote, and the order in which they are computed is fixed.

**Labor.** The chef's labor subtotal depends on the menu's `base_price_per_guest_cents` and the booking's `party_size`. Small parties carry a surcharge: when `party_size` is strictly less than 4, the per-guest rate is the menu's base price multiplied by 1.20 and then rounded half up to whole cents; when `party_size` is 4 or more, the per-guest rate is exactly the base price with no surcharge. The surcharge is applied to the per-guest rate and rounded **before** multiplying by the party size — that is, `labor_total_cents` is the rounded per-guest rate times `party_size`. A party of 4 takes the base rate; a party of 3 takes the surcharge.

**Grocery markup tier.** At confirmation the system computes an estimated ingredient subtotal as the menu's `estimated_ingredient_per_guest_cents` multiplied by `party_size`, and uses that whole subtotal to pick a single markup rate frozen into `locked_markup_rate`. The selection is by whole-subtotal threshold, not marginal slabs: if the subtotal is below 20000 cents the rate is 0.25; if the subtotal is at least 20000 but below 50000 cents the rate is 0.18; if the subtotal is 50000 cents or more the rate is 0.12. A subtotal of exactly 20000 selects 0.18, and 19999 selects 0.25; a subtotal of exactly 50000 selects 0.12. This rate is frozen for the life of the booking.

**Estimated grocery total.** Also at confirmation, `estimated_grocery_total_cents` is the estimated ingredient subtotal (the same `estimated_ingredient_per_guest_cents` times `party_size`) multiplied by one plus the locked markup rate, with half-up rounding applied once to the whole marked-up subtotal. This estimated figure is the provisional ingredient basis, and it is also the figure that is restored if a finalized grocery run is later voided by a cancellation.

**Travel.** `travel_fee_cents` is simply the flat fee of the resolved travel zone, carried unchanged.

**Quote and balance.** `quote_total_cents` is the sum of `labor_total_cents`, the current grocery basis, and `travel_fee_cents`, with no rounding — the addends are already whole cents. The grocery basis is `actual_grocery_total_cents` when a finalized grocery run exists for the booking, and `estimated_grocery_total_cents` otherwise; the basis is selected before the sum is taken. `balance_due_cents` is then `quote_total_cents` minus `amount_captured_cents`, always derived from the freshly computed quote rather than a stale one.

**Deposit.** `deposit_due_cents` is the confirmation-time quote (computed on the estimated grocery basis) multiplied by 0.30 and rounded half up to whole cents. The deposit is pinned once at confirmation and is never re-derived afterward, even when actual ingredient costs later change the quote; only `balance_due_cents` tracks the actual-cost quote.

### 3.5. Grocery Runs: From Receipts to the Finalized Quote

Once a booking is `CONFIRMED`, the chef opens a grocery run for it. A run is created with the parent `booking_id` and a `line_items` array, each line being a label and an `actual_cost_cents` receipt amount. A new run starts in `OPEN` status, which is editable; at this point the system computes its `raw_actual_subtotal_cents` (the sum of the line items' `actual_cost_cents`) but does not yet apply anything to the booking's quote. A booking has at most one grocery run; runs may be listed filtered by `booking_id` and `status`.

Finalizing the run is the chef's action that locks the receipts and re-pins the quote to real costs. It is allowed only when the acting chef owns the parent booking (`ERR_NOT_RESOURCE_OWNER`), the parent booking is `CONFIRMED` (`ERR_BOOKING_NOT_CONFIRMED`), and the run has at least one line item (`ERR_GROCERY_RUN_EMPTY`). On finalize, the run's `raw_actual_subtotal_cents` is recomputed as the sum of the lines' `actual_cost_cents`, and the `actual_grocery_total_cents` written to the parent booking is computed by a **per-line round-then-sum** method: for each line, in the order the line items were submitted, multiply that line's `actual_cost_cents` by one plus the booking's `locked_markup_rate` and round half up to whole cents; then sum those per-line rounded amounts. This is deliberately not the same as rounding the whole marked-up subtotal once — the two can differ by a cent of rounding drift, and the per-line method is the pinned one. The run moves to `FINALIZED`. The booking's `quote_total_cents` is re-pinned with the actual grocery basis now superseding the estimate, and `balance_due_cents` is recomputed from the new quote. The deposit is not touched.

A booking cannot move into preparation until its grocery run is finalized, and the balance payment cannot be taken until then either — both lean on the finalized run as the point at which the real ingredient cost is known.

### 3.6. Payments and Settlement

A booking's `payment_status` axis runs independently of its lifecycle. It begins at `UNPAID` and is advanced by payments, each of which is created with the owning `booking_id`, a `kind` of either `DEPOSIT` or `BALANCE`, and an `amount_cents` (at least 1). A payment is minted with `status` `CAPTURED`, carries a `refunded_cents` that starts at 0, and adds its amount to the booking's `amount_captured_cents`, after which `balance_due_cents` is recomputed.

A deposit payment is the first step. It requires that the booking's lifecycle is `CONFIRMED` (`ERR_BOOKING_NOT_CONFIRMED`), then that the booking's `payment_status` is still `UNPAID` — a deposit is rejected with `ERR_INVALID_STATE` once one has already been paid — and finally that the `amount_cents` exactly equals the booking's `deposit_due_cents` (`ERR_DEPOSIT_AMOUNT_MISMATCH`); these three are checked in that order. On success the booking's `payment_status` moves from `UNPAID` to `DEPOSIT_PAID`, and the chef's `captured_payments_cents` and `payout_accrued_cents` are recomputed. A balance payment is the second step: it first requires that `payment_status` is `DEPOSIT_PAID` — a balance attempted before the deposit, or after the booking is already paid in full, is rejected with `ERR_INVALID_STATE` — then that a finalized grocery run exists for the booking, since the balance is only billable once the actual cost is known (`ERR_GROCERY_RUN_NOT_FINALIZED`), and finally that `amount_cents` exactly equals the current `balance_due_cents` (`ERR_BALANCE_AMOUNT_MISMATCH`). On success `balance_due_cents` becomes 0, `payment_status` moves from `DEPOSIT_PAID` to `PAID_IN_FULL`, and the chef's captured and payout figures are recomputed again.

Preparation and completion close out the lifecycle. A chef starts prep on a `CONFIRMED` booking it owns, provided a finalized grocery run exists (`ERR_GROCERY_RUN_NOT_FINALIZED`); this moves `lifecycle_status` from `CONFIRMED` to `IN_PREP`. A chef completes an `IN_PREP` booking it owns only when its `payment_status` is `PAID_IN_FULL` (`ERR_BALANCE_OUTSTANDING`); completion moves `lifecycle_status` to `COMPLETED`, a terminal state. On completion the booking's `BOOKING_HOLD` remains in place as a record of consumed occupancy, but the chef's `active_booking_count` is decremented, its `completed_bookings_count` is incremented, and both its `settled_reliability_score` and `projected_reliability_score` are recomputed (§3.7).

The chef's money aggregates are kept consistent throughout. `captured_payments_cents` is the running sum across the chef's bookings of all `Payment.amount_cents` whose status is `CAPTURED` or `REFUNDED`; `refunded_payments_cents` is the running sum of all `Payment.refunded_cents`; and `payout_accrued_cents` is `captured_payments_cents` minus `refunded_payments_cents`. That identity holds after every capture and every refund — a cancel-and-refund pair never makes the payout drift from captured minus refunded.

### 3.7. Chef Reliability: Settled and Projected Scores

A chef carries two reliability scores that are recomputed whenever its bookings reach or change terminal status — on confirm, complete, decline, and cancel — and they are intentionally allowed to differ.

The **settled** score, `settled_reliability_score`, looks only at the chef's terminal bookings: those in `COMPLETED`, `DECLINED`, or `CANCELLED`. Starting from a base of 50, it walks those terminal bookings in chronological order — ascending by `event_start_utc`, breaking ties by ascending `created_at` (and never by `id`) — and accumulates: a `COMPLETED` booking adds 10, a `DECLINED` booking subtracts 8 (the chef turned a request away), and a `CANCELLED` booking adds nothing, since the cancellation is client-initiated and neutral to the chef. After accumulating, the running total is clamped to the inclusive range 0 to 100 to produce the settled score.

The **projected** score, `projected_reliability_score`, is forward-looking. It takes the same chronological accumulation as the settled score **before** that final clamp is applied, then adds 10 for each of the chef's bookings currently in `CONFIRMED` or `IN_PREP` — counting not-yet-completed work optimistically as if it will complete — and clamps that sum to the inclusive range 0 to 100. Because the base is 50, well below the ceiling of 100, the projected score is observably higher than the settled score whenever the chef has any `CONFIRMED` or `IN_PREP` bookings, and equals it when there are none.

### 3.8. Cancellation: Lead-Time Refunds and the Void Cascade

A client may cancel a booking it owns while that booking is `REQUESTED`, `CONFIRMED`, or `IN_PREP` (`ERR_NOT_RESOURCE_OWNER` if the caller is not the owning client). Cancellation is the system's largest cascade, and every effect lands atomically.

First the refund fraction is determined from lead time. The lead time is the whole number of days from the current clock to the booking's `event_start_utc`, computed by taking the difference in seconds, dividing by 86400 seconds per day, and flooring to a whole number of days. If the lead time is at least 14 days, `cancellation_refund_rate` is 1.00 (full refund); if it is at least 7 but fewer than 14 days, the rate is 0.50; otherwise the rate is 0.00. At the boundaries: 14 days gives a full refund, 13 days gives half, 7 days gives half, and 6 days gives nothing.

Each of the booking's `CAPTURED` payments is then refunded by setting its `refunded_cents` to its `amount_cents` multiplied by the refund rate, rounded half up per payment; a payment whose refund equals its full amount has its `status` moved to `REFUNDED`. The booking's `amount_refunded_cents` mirror is updated. If any refund was issued (the rate was above 0), the booking's `payment_status` moves to `REFUNDED`.

If the booking has a `FINALIZED` grocery run, that run transitions to `VOIDED`, which zeroes the booking's `actual_grocery_total_cents` and re-pins `quote_total_cents` back to the estimated grocery basis (the estimated-vs-actual swap of §3.4 in reverse); `balance_due_cents` is recomputed from that re-pinned quote. If the booking had been `CONFIRMED` or `IN_PREP`, its `BOOKING_HOLD` availability block is moved to `RELEASED` so the slot is freed, and the chef's `active_booking_count` is decremented to restore capacity. A booking cancelled while still `REQUESTED` never minted a hold, so none is released. Finally `lifecycle_status` moves to `CANCELLED` (terminal), and the chef's `captured_payments_cents`, `refunded_payments_cents`, and `payout_accrued_cents` are recomputed to keep the payout invariant, along with the chef's `projected_reliability_score`.

### 3.9. Rescheduling a Confirmed Booking

Either party may propose moving a booking. A reschedule request is created with the parent `booking_id`, a `proposed_event_start_utc`, and a `proposed_event_end_utc` (the proposed end strictly after the proposed start). Creating the request imposes no precondition on the parent booking's `lifecycle_status`: the create operation checks only that the caller is a party to the booking (ownership), and does **not** itself reject a non-`CONFIRMED` booking — the `CONFIRMED` requirement (`ERR_BOOKING_NOT_CONFIRMED`) is enforced only at acceptance, not at creation. The new request starts in `PROPOSED` status, and its `requested_by_role` is recorded from the caller's role as either `CLIENT` or `CHEF`; this is recorded for the audit trail but has no fiscal effect. Requests may be listed filtered by `booking_id` and `status`.

A chef accepts a `PROPOSED` request on a booking it owns, but only when the parent booking is `CONFIRMED` (`ERR_BOOKING_NOT_CONFIRMED`) and the proposed window — widened by the chef's prep buffer, running from `proposed_event_start_utc` minus `prep_buffer_minutes` to `proposed_event_end_utc` — does not overlap any of the chef's `HELD` availability blocks **except** the booking's own current hold, which is expected to overlap and is excluded from the check (`ERR_CHEF_TIME_CONFLICT`). Acceptance updates the booking's `event_start_utc`, `event_end_utc`, and `event_date` to the proposed window; it releases the booking's old `BOOKING_HOLD` and mints a fresh `HELD` hold over the proposed window. The request moves to `ACCEPTED` (terminal), and any sibling `PROPOSED` requests on the same booking are moved to `WITHDRAWN`.

A chef may reject a `PROPOSED` request on a booking it owns, moving it to `REJECTED` (terminal) and leaving the booking window unchanged. A client may withdraw its own `PROPOSED` request on a booking it owns, moving it to `WITHDRAWN` (terminal). The three outcomes — acceptance by the chef, rejection by the chef, withdrawal by the client — are the only exits from `PROPOSED`.

### 3.10. Recurring Meal-Prep Plans

A client can set up a recurring meal-prep plan that spawns bookings on a cadence. A plan is created with the serving `chef_id`, the owning `client_id`, the repeated `menu_package_id`, a `party_size` used for every occurrence, a `service_zip` for every occurrence, a `weekday` (the day occurrences land on, 0 for Monday through 6 for Sunday), an `event_start_time_utc` (the `HH:MM:SS` UTC time of day each occurrence starts), a `duration_minutes` (each occurrence's length, at least 1), and an optional `cadence_weeks` (weeks between occurrences, where 1 is weekly and 2 is biweekly, defaulting to 1 and at least 1). A new plan starts `ACTIVE` with `occurrences_generated` at 0.

Generating an occurrence spawns the next booking from an `ACTIVE` plan for a supplied `occurrence_date`. The spawned booking is created in `REQUESTED` status with its `recurring_plan_id` set to the plan, its event window derived from the plan's time of day and duration on the occurrence date, and the plan's `occurrences_generated` incremented by one. The spawned booking then follows the ordinary confirmation, payment, and completion path.

A plan owner may pause an `ACTIVE` plan, moving its `status` to `PAUSED`. Pausing is a depth-two cascade: every child booking spawned by the plan that is still in `REQUESTED` is cancelled with a refund rate of 0 (none have been paid), and any such child that happened to hold a `BOOKING_HOLD` has that block moved to `RELEASED`. A paused plan generates nothing further until resumed. A `PAUSED` plan may be resumed back to `ACTIVE` by its owner, after which generation is allowed again. A plan may be cancelled by its owner from either `ACTIVE` or `PAUSED`, moving its `status` to `CANCELLED` (terminal); no further occurrences may ever be generated from a cancelled plan. All plan transitions require the acting client to own the plan (`ERR_NOT_RESOURCE_OWNER`).

### 3.11. The Test Clock

Because lead-time refunds and chronological reliability ordering depend on the current time, the platform exposes an administrative test-driving capability that pins the system clock to a supplied `now_utc` instant. Only a `PlatformAdmin` may use it. Once set, that instant is the clock used for all subsequent lead-time and temporal computations until it is set again.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Creating a new resource returns HTTP 201 with the created resource in `data`; state transitions and other modifications return HTTP 200 with the updated resource; successful reads return HTTP 200. Error responses use the catalogue in §5. Request bodies, response payloads, and side effects are not restated here — they are specified in the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | /chefs | Register a new chef (DRAFT) | Chef, PlatformAdmin |
| GET | /chefs | List chefs (paginated) | Chef, Client, PlatformAdmin |
| GET | /chefs/{chefId} | Get a chef including computed scores and payout fields | Chef, Client, PlatformAdmin |
| POST | /chefs/{chefId}/activate | Activate a chef (DRAFT or SUSPENDED to ACTIVE) | Chef, PlatformAdmin |
| POST | /chefs/{chefId}/suspend | Suspend a chef (ACTIVE to SUSPENDED) | PlatformAdmin |
| POST | /menus | Create a menu package (unlisted) | Chef |
| GET | /menus | List menu packages; filter by chef_id, is_listed | Chef, Client, PlatformAdmin |
| GET | /menus/{menuId} | Get a menu package | Chef, Client, PlatformAdmin |
| POST | /menus/{menuId}/publish | Publish a menu package | Chef |
| POST | /travel-zones | Create a travel zone with a flat fee | Chef |
| GET | /travel-zones | List travel zones; filter by chef_id | Chef, Client, PlatformAdmin |
| GET | /travel-zones/{zoneId} | Get a travel zone | Chef, Client, PlatformAdmin |
| POST | /availability-blocks | Create a BLACKOUT availability block | Chef |
| GET | /availability-blocks | List availability blocks; filter by chef_id, booking_id, status, kind | Chef, Client, PlatformAdmin |
| GET | /availability-blocks/{blockId} | Get an availability block | Chef, Client, PlatformAdmin |
| POST | /clients | Register a client | Client, PlatformAdmin |
| GET | /clients/{clientId} | Get a client | Client, Chef, PlatformAdmin |
| POST | /bookings | Create a booking request (REQUESTED) | Client |
| GET | /bookings | List bookings; filter by chef_id, client_id, recurring_plan_id, menu_package_id, travel_zone_id, lifecycle_status, event_date | Chef, Client, PlatformAdmin |
| GET | /bookings/{bookingId} | Get a booking including computed totals | Chef, Client, PlatformAdmin |
| POST | /bookings/{bookingId}/confirm | Chef confirms a REQUESTED booking; OCC-guarded on Chef.version | Chef |
| POST | /bookings/{bookingId}/decline | Chef declines a REQUESTED booking | Chef |
| POST | /bookings/{bookingId}/cancel | Client cancels a REQUESTED/CONFIRMED/IN_PREP booking | Client |
| POST | /bookings/{bookingId}/start-prep | Chef moves a CONFIRMED booking to IN_PREP | Chef |
| POST | /bookings/{bookingId}/complete | Chef completes an IN_PREP booking | Chef |
| POST | /payments | Client makes a DEPOSIT or BALANCE payment | Client |
| GET | /payments | List payments; filter by booking_id | Chef, Client, PlatformAdmin |
| GET | /payments/{paymentId} | Get a payment | Chef, Client, PlatformAdmin |
| POST | /grocery-runs | Open a grocery run for a CONFIRMED booking | Chef |
| GET | /grocery-runs | List grocery runs; filter by booking_id, status | Chef, Client, PlatformAdmin |
| GET | /grocery-runs/{groceryRunId} | Get a grocery run | Chef, Client, PlatformAdmin |
| POST | /grocery-runs/{groceryRunId}/finalize | Finalize an OPEN grocery run and re-pin the quote | Chef |
| POST | /reschedule-requests | Propose a reschedule of a CONFIRMED booking | Client, Chef |
| GET | /reschedule-requests | List reschedule requests; filter by booking_id, status | Chef, Client, PlatformAdmin |
| GET | /reschedule-requests/{requestId} | Get a reschedule request | Chef, Client, PlatformAdmin |
| POST | /reschedule-requests/{requestId}/accept | Chef accepts a PROPOSED reschedule | Chef |
| POST | /reschedule-requests/{requestId}/reject | Chef rejects a PROPOSED reschedule | Chef |
| POST | /reschedule-requests/{requestId}/withdraw | Client withdraws its own PROPOSED reschedule | Client |
| POST | /recurring-plans | Create a recurring meal-prep plan (ACTIVE) | Client |
| GET | /recurring-plans | List recurring plans; filter by chef_id, client_id, menu_package_id, status | Chef, Client, PlatformAdmin |
| GET | /recurring-plans/{planId} | Get a recurring plan | Chef, Client, PlatformAdmin |
| POST | /recurring-plans/{planId}/generate-occurrence | Spawn the next booking occurrence from an ACTIVE plan | Client |
| POST | /recurring-plans/{planId}/pause | Pause an ACTIVE plan; cascade-cancel REQUESTED children | Client |
| POST | /recurring-plans/{planId}/resume | Resume a PAUSED plan | Client |
| POST | /recurring-plans/{planId}/cancel | Cancel a plan (terminal) | Client |
| POST | /_clock/set | Pin the system clock for lead-time and temporal computations | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_MISSING_AUTH_CONTEXT | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_CHEF_NOT_FOUND | 404 |
| ERR_MENU_NOT_FOUND | 404 |
| ERR_ZONE_NOT_FOUND | 404 |
| ERR_CLIENT_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_RESCHEDULE_NOT_FOUND | 404 |
| ERR_GROCERY_RUN_NOT_FOUND | 404 |
| ERR_BLOCK_NOT_FOUND | 404 |
| ERR_PAYMENT_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_CHEF_NOT_ACTIVE | 409 |
| ERR_BOOKING_NOT_CONFIRMED | 409 |
| ERR_GROCERY_RUN_NOT_FINALIZED | 409 |
| ERR_GROCERY_RUN_EMPTY | 422 |
| ERR_ALLERGEN_CONFLICT | 422 |
| ERR_EQUIPMENT_UNAVAILABLE | 422 |
| ERR_PARTY_SIZE_OUT_OF_RANGE | 422 |
| ERR_ZIP_OUTSIDE_SERVICE_AREA | 422 |
| ERR_CHEF_TIME_CONFLICT | 409 |
| ERR_DAILY_CAPACITY_EXCEEDED | 409 |
| ERR_NO_LISTED_MENU | 409 |
| ERR_NO_TRAVEL_ZONE | 409 |
| ERR_DEPOSIT_AMOUNT_MISMATCH | 402 |
| ERR_BALANCE_AMOUNT_MISMATCH | 402 |
| ERR_BALANCE_OUTSTANDING | 402 |
