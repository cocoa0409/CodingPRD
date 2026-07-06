# Mobile Bartending & Catering API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a mobile bartending and beverage-catering business. The company travels to a host's venue, sets up a mobile bar, staffs it with certified bartenders, and pours drinks for a private event. Crucially, the business operates a strict **host / no-sale (BYOB) model**: the host owns and supplies all the alcohol, and the company never sells a single drink. That legal posture is not a footnote — it is the spine of the product. Before any bartender can be locked onto an event, a compliance officer must independently verify the host's liquor-liability insurance, the host's attestation of alcohol ownership, and every assigned bartender's responsible-service certification. Until that sign-off lands, staffing and service are gated.

The platform coordinates five kinds of actors around a single hub entity, the **Event**. A host (the client) books an event and picks a beverage-catering package; the system immediately quotes provisional pricing, a required deposit, a BYOB shopping estimate, and how many bartenders the guest count demands. Operations staff then run the machinery behind the scenes — opening the compliance review, scheduling bartenders and bar kits within non-overlapping time windows, generating the inventory plan, running the event, and reconciling any broken glassware afterward. Payments, refunds, cancellation fees, and breakage charges all flow through a single money ledger attached to the event so that the balance always reconciles.

Because bookings evolve — guest counts change, schedules shift, compliance findings reopen — the system leans heavily on derived state and optimistic concurrency. An event carries two independent lifecycle dimensions (a booking track and a payment track) plus a compliance posture derived from its review. Many operations cascade: clearing or re-opening compliance ripples into assignments; cancelling a confirmed event triggers refunds and un-staffing; settling a breakage report posts a charge back onto the event balance. This specification defines every field, every state transition, every calculation, and every rejection an implementer must reproduce.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the caller's role. If either header is missing, or if `X-User-Role` is not one of the five recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well formed but the role is not permitted to perform the requested operation — or an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The five roles are spelled exactly as follows: `PlatformAdmin`, `Client`, `Coordinator`, `ComplianceOfficer`, and `Bartender`.

- **`PlatformAdmin`** manages catalog configuration: creating packages, registering bartenders, adding bar kits, and registering clients. Its identity is opaque — when `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`.
- **`Client`** is the host who books and pays for events. This role is entity-backed: when `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`. Ownership checks on any event compare the event's `client_id` to `X-User-ID`; a client may only read, edit, pay, confirm, cancel, or add menu items to an event whose `client_id` equals its own `X-User-ID`.
- **`Coordinator`** is operations staff who run compliance, staffing, kits, inventory, service, and breakage. Its identity is opaque — `X-User-ID` is an operator identifier the server may record but does not compare to any entity's `id`.
- **`ComplianceOfficer`** performs independent compliance sign-off. Its identity is likewise opaque and is not tied to any persisted entity.
- **`Bartender`** is assigned staff who check in to their own shifts. This role is entity-backed: when `X-User-Role` is `Bartender`, `X-User-ID` is the `id` of the acting `Bartender`. Ownership checks compare an assignment's `bartender_id` to `X-User-ID`; a bartender may only check in to (or cancel) an assignment whose `bartender_id` equals its own `X-User-ID`.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and may be no smaller than 0. Results are always returned sorted by `created_at` in ascending order (oldest first). List responses populate `limit`, `offset`, `total_count`, and `has_more` in the `meta` block, where `total_count` is the count of all rows matching the filter before pagination is applied and `has_more` is true when more rows exist beyond the current page.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, fixed at creation.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `version` starts at 1 on creation and increments by exactly 1 on every mutation of that resource; `updated_at` is refreshed to the current time on every mutation. These two fields are the backbone of change tracking and of the concurrency control described in §2.5. The one exception is the **`Payment`** resource: a payment is an immutable ledger record and carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version` field. All other resources (`Client`, `Package`, `Bartender`, `BarKit`, `Event`, `ComplianceReview`, `Assignment`, `KitReservation`, `InventoryPlan`, `BreakageReport`) carry the full set.

### 2.5. Optimistic Concurrency Control on Events

Two write operations against an event are guarded by optimistic concurrency control keyed on the event's `version`. In both cases the request body must include a non-optional field named `expected_event_version` carrying the client's last observed `version` of the target event. Before the write is applied, the server compares `expected_event_version` to the event's current `version`; if they do not match, the write is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412) and no change is made.

The first guarded operation is editing an event. Because a prior edit — or a payment or a compliance side effect — may already have advanced the event's `version`, a client holding a stale `expected_event_version` is refused. Two strictly sequential edits that each carry the same expected version cannot both apply: the first advances the version, and the second is therefore stale.

The second guarded operation is creating an assignment against an event. The prior assignment-create advanced the event's `version` because the staffing view changed, so a subsequent create still carrying the old `expected_event_version` is refused as stale; the losing writer resolves deterministically through the version check rather than by timing. Endpoints other than these two do not accept an `expected_event_version` field.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Wherever a calculation calls for rounding, the rounding method is **round half up** applied at each rounding step named in the formula. Guest-count servings and unit conversions that call for rounding up use the ceiling (round toward the next whole unit). Reliability scores are integers in the range 0 to 100, also rounded half up. Where a formula composes multiple rounding steps, they are applied in the order the formula states — intermediate results are not carried at higher precision past a named rounding step.

### 2.7. Nested Resource Retrieval and Validation Ordering

Many resources are addressed through a nested path — a compliance review, assignment, kit reservation, inventory plan, menu item, payment, or breakage report is reached beneath its parent event. Path parameters are validated left to right: the parent event is resolved first and, if its `id` does not resolve, the request fails with `ERR_EVENT_NOT_FOUND` (HTTP 404) before any child is considered. Only then is the child resource resolved, and only then are foreign-key targets in the body (client, package, bartender, or bar kit) checked.

Requests are validated in a fixed priority order, and the first failing check determines the error returned:

1. **Authentication** — headers present and role known, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role is permitted for the endpoint and, for entity-backed roles, owns the resource, else `ERR_UNAUTHORIZED`.
3. **Existence** — every path and body-referenced resource resolves. A missing event yields `ERR_EVENT_NOT_FOUND`; a missing assignment `ERR_ASSIGNMENT_NOT_FOUND`; a missing compliance review `ERR_COMPLIANCE_REVIEW_NOT_FOUND`; a missing kit reservation `ERR_KIT_RESERVATION_NOT_FOUND`; a missing breakage report `ERR_BREAKAGE_REPORT_NOT_FOUND`; a missing `client_id` `ERR_CLIENT_NOT_FOUND`; a missing `package_id` `ERR_PACKAGE_NOT_FOUND`; a missing `bartender_id` `ERR_BARTENDER_NOT_FOUND`; a missing `kit_id` `ERR_BARKIT_NOT_FOUND`.
4. **Body well-formedness** — required fields present, enum members valid, numeric ranges satisfied, and every time range strictly ordered, else `ERR_VALIDATION` (HTTP 400).
5. **Optimistic concurrency** — on the two guarded event writes, `expected_event_version` must equal the current `version`, else `ERR_STALE_EVENT_VERSION`.
6. **State legality** — the target resource is in a status from which the requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409). Terminal states reject every transition, and re-issuing a transition already applied is likewise an invalid-state rejection.
7. **Business-safety, temporal, and fiscal checks** — the domain-specific rules described in §3, evaluated after the preceding gates pass.

This ordering matters: for example, a stale-version edit is rejected before any state or business check runs, and a body that fails well-formedness is rejected before concurrency is examined.

### 2.8. Compliance Posture and Cascading Consistency

An event's `compliance_posture` is a computed dimension derived from its compliance review. It reads `PENDING` while no review has been cleared, `CLEARED` once the review reaches `CLEARED`, and `BLOCKED` when a previously cleared review is re-opened by a later request for changes. Posture is the gate for staffing and confirmation: assignments cannot be confirmed and events cannot be confirmed unless posture is `CLEARED`.

Whenever an operation mutates a resource, that resource's `version` increments by 1 and its `updated_at` refreshes. Operations that cascade across entities mutate each affected resource the same way. Two cascades in particular reshape child state: clearing a review lifts the parent event's posture to `CLEARED`, and requesting changes on a review — whether from `SUBMITTED` or from `CLEARED` — drives the posture to `BLOCKED` and reverts every child assignment currently in `CONFIRMED` back to `PROPOSED`, recomputing the affected bartenders' reliability. Those cascades are detailed in §3.4 and §3.5.

### 2.9. Temporal Windowing for Staffing and Kits

Both bartender shifts and bar-kit reservations are time windows, and the system enforces non-overlap, but with different rules. A bartender's shift is dilated by a **travel buffer of 90 minutes** on each side before overlap is tested against that bartender's other non-terminal shifts; because of the buffer, even shifts that merely sit close together are treated as conflicting. A bar-kit reservation, by contrast, is tested with no buffer: two reservations for the same kit conflict only when their half-open intervals actually overlap, and exact adjacency — one window ending precisely when the next begins — is permitted.

## 3. Business Logic & Workflows

### 3.1. Configuring the Catalog and Roster

Before any event can be booked, a `PlatformAdmin` seeds the catalog. A **package** captures a beverage-catering tier and its pricing model. Each package carries a `tier` (one of `BEER_WINE`, `CLASSIC`, `PREMIUM`, or `LUXURY`), a display `name`, a `base_price_cents` (at least 0) that covers a bundle of included guests and hours, an `included_guest_count` (at least 1) and a `per_guest_overage_cents` (at least 0) charged for each guest above that bundle, an `included_hours` (at least 1) and a `per_hour_overage_cents` (at least 0) charged for each whole billable hour above that bundle, and a `min_hours` (at least 1) recording the fewest billable hours the package is intended to be booked for — `min_hours` is validated (at least 1) and stored on the package but is not enforced as a booking-time constraint on events. Two operational ratios round out the package: `drinks_per_guest_per_hour` (greater than 0), which feeds the BYOB inventory estimate, and `guests_per_bartender` (at least 1), the staffing ratio that determines how many bartenders an event needs. A package also carries an `is_active` flag that defaults to true and governs whether it may be selected on new events.

A **bartender** is registered with a `full_name`, an `email`, a `certification_expiry` (the ISO 8601 UTC moment the responsible-service certification lapses), an `hourly_rate_cents` labor rate (at least 0), and a `home_state_code` (a two-letter uppercase US state code) identifying the jurisdiction the bartender is licensed to serve. On registration the bartender's `availability_status` is set to `AVAILABLE`, its `upcoming_assignment_count` is 0, and both reliability scores — `reliability_score_strict` and `reliability_score_lenient` — are initialized to 100 to reflect an empty history. Availability moves among `AVAILABLE` (bookable), `ENGAGED` (holds upcoming assignments), and `INACTIVE` (retired from the pool); deactivating a bartender sets `availability_status` to `INACTIVE`.

A **bar kit** is the physical station. It carries a `kit_name`, a `station_type` (one of `BEER_WINE`, `FULL_BAR`, or `MOBILE_CART`), a `glassware_count` (at least 0) of reusable glasses, and a `status` that begins `AVAILABLE` and may become `RETIRED` when removed from the fleet. Finally, a **client** — the host — is registered with a `full_name`, `email`, `phone`, and a `home_state_code` (two-letter uppercase) for the billing address.

### 3.2. Booking an Event and the Provisional Quote

A `Client` books an event by supplying the host's own `client_id`, the chosen `package_id`, a `title`, a `venue_state_code` (two-letter uppercase, the ABC jurisdiction), a `venue_type` (one of `INDOOR`, `OUTDOOR`, or `MIXED`), a scheduled `event_start` and `event_end` (ISO 8601 UTC, with `event_end` strictly after `event_start`), and a `guest_count` of at least 1. An optional `byob_host_model` flag defaults to true and records that the host owns and supplies all alcohol. On creation the event opens with `booking_status` of `DRAFT`, `payment_status` of `UNPAID`, and `compliance_posture` of `PENDING`.

At booking time the system derives every downstream figure. The **billable hours** (`billable_hours`) are the duration from `event_start` to `event_end`, expressed in hours and rounded up to the next whole hour. The **required bartender count** (`required_bartender_count`) is the `guest_count` divided by the package's `guests_per_bartender`, rounded up to the next whole bartender.

Pricing is computed by a tiered model that produces both a provisional and a final figure. The number of **overage guests** is the amount by which `guest_count` exceeds the package's `included_guest_count`, or zero if it does not exceed it. The **subtotal** (`subtotal_cents`) is the package's `base_price_cents`, plus the overage guests multiplied by `per_guest_overage_cents`, plus the number of overage hours multiplied by `per_hour_overage_cents`. Overage hours are computed two ways. In the **final** variant, the overage hours are the amount by which `billable_hours` exceeds the package's `included_hours`, or zero otherwise. In the **provisional** variant used at quote time, overage hours are treated as zero regardless of the actual duration — the provisional figure always assumes the event fits inside the included hours. The two variants coincide only when `billable_hours` does not exceed `included_hours`.

On top of the subtotal sit a service fee and gratuity. The **service fee** (`service_fee_cents`) starts as the subtotal multiplied by a tiered percentage selected by guest count: 20 percent when `guest_count` is 50 or fewer, 18 percent when it is between 51 and 150 inclusive, and 15 percent when it is above 150. That rounded product is then clamped to lie between a floor of 25000 cents and a ceiling of 200000 cents — if the rounded product falls below the floor it is raised to 25000, and if it rises above the ceiling it is capped at 200000. The **gratuity** (`gratuity_cents`) is the subtotal multiplied by 18 percent, rounded. The **final grand total** (`final_grand_total_cents`) is the subtotal plus the service fee plus the gratuity. The **provisional grand total** (`provisional_grand_total_cents`) is the same composition computed under the provisional (zero overage-hours) subtotal.

The **deposit due** (`deposit_due_cents`) is the provisional grand total multiplied by 50 percent, rounded. Payments accumulate into `amount_paid_cents`, defined as the sum of all `DEPOSIT` and `BALANCE` payment amounts less the sum of all `REFUND` amounts. The **balance due** (`balance_due_cents`) for a non-terminal event is the final grand total, plus every `BREAKAGE_CHARGE` and every `CANCELLATION_FEE` posted against the event, less `amount_paid_cents`; for a cancelled event the balance is reconciled to zero.

A `Client` may edit an event's `guest_count`, `event_start`, `event_end`, or `venue_type` while supplying `expected_event_version` for the concurrency check described in §2.5. Any such edit recomputes both pricing variants, the deposit due, the balance due, and the required bartender count, and marks any existing inventory plan as stale by setting its `status` to `STALE`. Reads of an event always reflect the current computed financial and posture fields.

### 3.3. The Payment Ledger

A `Client` records money against an event by posting a payment whose `payment_type` is `DEPOSIT` or `BALANCE`, an `amount_cents` of at least 1, and a `method` (one of `CARD`, `ACH`, `CASH`, or `SYSTEM`, defaulting to `SYSTEM`). Client-supplied payments are always deposits or balances; the reconciliation types `REFUND`, `CANCELLATION_FEE`, and `BREAKAGE_CHARGE` are created only by the server, which supplies their `amount_cents` and marks their `method` as `SYSTEM`. Every payment references its event through `event_id`.

Posting a payment recomputes `amount_paid_cents` and `balance_due_cents` and advances `payment_status`. The first deposit moves `payment_status` from `UNPAID` to `DEPOSIT_PAID`; once the balance due reaches zero the status advances to `PAID_IN_FULL`. A `BALANCE` payment may not exceed the current `balance_due_cents`, and a `DEPOSIT` posted while the `payment_status` is anything other than `UNPAID` — including a second deposit after the status already reads `DEPOSIT_PAID` — is refused; either violation returns `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422). Payment records, including the system-created refunds and fees, may be listed for an event.

### 3.4. The Compliance Review Lifecycle

Compliance is the gate that legitimizes staffing. A `Coordinator` opens a review for an event by attesting four facts: the `abc_model` (one of `HOST_NO_SALE`, `CASH_BAR`, or `NONE`), whether the host's `liquor_liability_insurance_verified` is true, whether `host_alcohol_ownership_attested` is true, and whether `server_certification_verified` is true. The review is created in `DRAFT` with `revision_round` at 0 and carries optional `reviewer_notes`. It references its event via `event_id`.

A review moves through a cyclic lifecycle and is never terminal. The coordinator submits it, advancing `DRAFT → SUBMITTED`; a submit may also correct any of the four attestations along the way. From `SUBMITTED`, a `ComplianceOfficer` either clears it or requests changes. Clearing (`SUBMITTED → CLEARED`) is permitted only when all four conditions hold: `abc_model` equals `HOST_NO_SALE`, `liquor_liability_insurance_verified` is true, `host_alcohol_ownership_attested` is true, and `server_certification_verified` is true. If `abc_model` is not `HOST_NO_SALE`, clearing fails with `ERR_ABC_MODEL_INVALID` (HTTP 422); if the insurance is not verified, it fails with `ERR_INSURANCE_NOT_VERIFIED` (HTTP 422); if either the host attestation or the server-certification attestation is false, it fails with `ERR_HOST_ATTESTATION_MISSING` (HTTP 422). A successful clear sets the review's `status` to `CLEARED` and lifts the parent event's `compliance_posture` to `CLEARED`.

Requesting changes drives the review to `CHANGES_REQUESTED` and requires `reviewer_notes`. It is allowed from either `SUBMITTED` or `CLEARED`. When it fires, three effects cascade: the parent event's `compliance_posture` moves to `BLOCKED`; because the event is now blocked, every child assignment currently in `CONFIRMED` reverts to `PROPOSED`; and each reverted assignment's bartender has their reliability scores recomputed, though the `upcoming_assignment_count` is unchanged because the assignment remains upcoming as `PROPOSED`. From `CHANGES_REQUESTED`, the coordinator resubmits, advancing `CHANGES_REQUESTED → SUBMITTED` and incrementing `revision_round` by 1 on each resubmission. A cleared review may be re-opened by a later request for changes if a re-inspection finds an issue, running the same block-and-revert cascade.

### 3.5. Staffing: Assignments, Scheduling, and Reliability

A `Coordinator` schedules a bartender onto an event by creating an assignment. The create supplies the `bartender_id`, a `shift_start` and `shift_end` (ISO 8601 UTC, with `shift_end` strictly after `shift_start`; the shift may begin before `event_start` to allow setup), a `role_on_event` of either `LEAD` or `BACK`, and `expected_event_version` for the concurrency guard. The new assignment opens in `PROPOSED` and references its event via `event_id`. Because assignment creation is a guarded event write, a stale `expected_event_version` is rejected with `ERR_STALE_EVENT_VERSION` before any staffing check runs.

Several safety checks guard the create, and they surface distinct errors. The bartender's `certification_expiry` must fall strictly after the event's `event_start`; a certification that has lapsed by service time is rejected with `ERR_BARTENDER_CERT_EXPIRED` (HTTP 422). The bartender's `home_state_code` must equal the event's `venue_state_code`, since the bartender must be licensed in the venue's ABC jurisdiction; a mismatch is rejected with `ERR_JURISDICTION_MISMATCH` (HTTP 422). Scheduling conflicts are caught by the travel-buffer overlap rule of §2.9: if the new shift, extended by 90 minutes on both sides, overlaps any other non-terminal shift held by the same bartender, the create is rejected with `ERR_BARTENDER_DOUBLE_BOOKED` (HTTP 409). Only after the double-booking check does availability gate the create: the bartender's `availability_status` must be `AVAILABLE` or `ENGAGED` — an `INACTIVE` bartender cannot be assigned and yields `ERR_BARTENDER_UNAVAILABLE` (HTTP 409). A `LEAD` assignment additionally requires that the bartender's `reliability_score_strict` be at least 70; a lower strict score is rejected with `ERR_INSUFFICIENT_RELIABILITY` (HTTP 422), while `BACK` assignments carry no reliability gate.

On a successful create the system computes the shift's labor figures and books the bartender. The **shift hours** (`shift_hours`) are the duration from `shift_start` to `shift_end` in hours, rounded up to the nearest quarter hour. The **labor cost** (`labor_cost_cents`) treats the first 8 shift hours as regular time and any hours beyond 8 as overtime: it is the regular hours multiplied by the bartender's `hourly_rate_cents`, plus the overtime hours multiplied by `hourly_rate_cents` and again by an overtime multiplier of 1.5, with the total rounded. Creating the assignment increments the bartender's `upcoming_assignment_count` and sets `availability_status` to `ENGAGED`.

Assignments then move through their own lifecycle. A coordinator confirms a proposed assignment, advancing `PROPOSED → CONFIRMED`, but only when the parent event's `compliance_posture` is `CLEARED`; a confirm attempted while posture is not cleared is rejected with `ERR_COMPLIANCE_NOT_CLEARED` (HTTP 409). The assigned `Bartender` — and only that bartender, matched by ownership — checks in on the day of service, advancing `CONFIRMED → CHECKED_IN`. A coordinator may mark a confirmed bartender a no-show, advancing `CONFIRMED → NO_SHOW`, which sets `cancelled_by` to `SYSTEM`, decrements the bartender's `upcoming_assignment_count`, and recomputes reliability. Either a coordinator or the owning bartender may cancel an assignment while it is `PROPOSED` or `CONFIRMED`, advancing it to `CANCELLED` with `cancelled_by` set to the acting role spelled in upper case (`COORDINATOR` for a coordinator cancel, `BARTENDER` for the owning bartender), decrementing `upcoming_assignment_count`, and recomputing reliability. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal.

Both reliability scores are recomputed on any assignment transition into `COMPLETED`, `NO_SHOW`, or `CANCELLED`. Let *completed* be the count of the bartender's assignments in `COMPLETED`, *no-shows* the count in `NO_SHOW`, and *cancels* the count in `CANCELLED` whose `cancelled_by` is `BARTENDER`; let *total* be the sum of those three. When *total* is zero, both scores are 100. Otherwise the **strict score** (`reliability_score_strict`) is 100 multiplied by completed divided by total, then reduced by 15 for each no-show and by 5 for each bartender cancel, rounded, and floored at 0. The **lenient score** (`reliability_score_lenient`) is 100 multiplied by the quantity (completed plus half of cancels) divided by total, then reduced by 8 for each no-show, rounded, and floored at 0. The strict score gates `LEAD` eligibility (it must be at least 70); the lenient score is a display metric only.

### 3.6. Bar Kits, Deployment, Inventory, and Menu

A `Coordinator` reserves a bar kit for an event's window by supplying the `kit_id`, a `reserve_start`, and a `reserve_end` (ISO 8601 UTC, with `reserve_end` strictly after `reserve_start`, spanning load-in through tear-down). The reservation opens in `RESERVED` and references its event via `event_id`. Reservations obey the no-buffer overlap rule of §2.9: if the new half-open window overlaps any other non-terminal reservation for the same kit, the create is rejected with `ERR_KIT_DOUBLE_BOOKED` (HTTP 409), though exact end-to-start adjacency is allowed. A reservation may be deployed once the event is in service — deploying advances `RESERVED → DEPLOYED` and snapshots the kit's `glassware_count` into the reservation's `items_checked_out`, establishing the glassware conservation baseline; deployment is only permitted while the reservation is in `RESERVED` and the parent event's `booking_status` is `IN_PROGRESS`, else the deploy is rejected with `ERR_INVALID_STATE` (HTTP 409). A deployed kit is later returned, advancing `DEPLOYED → RETURNED`. A reserved kit that is never deployed may instead be released, advancing `RESERVED → RELEASED`. `RETURNED` and `RELEASED` are terminal.

The BYOB **inventory plan** translates the guest experience into a shopping list, and it is generated (or regenerated when stale) for an event. Exactly one plan exists per event, referencing it via `event_id`, and it opens with `status` of `GENERATED`, flipping to `STALE` whenever the event is edited. Both an initial generation and a regeneration over the existing (possibly `STALE`) plan — which recomputes the figures in place and resets `status` to `GENERATED` — return HTTP 201. The rounding order is pinned: first the total is rounded up, then split by ratio, the remainder assigned to spirits, and only then converted to purchase units. The **total servings** (`total_servings`) are the `guest_count` multiplied by `billable_hours` multiplied by the package's `drinks_per_guest_per_hour`, rounded up to a whole serving. Of those, the beer servings are the total servings multiplied by 40 percent (rounded) and the wine servings are the total servings multiplied by 30 percent (rounded); the spirit servings are whatever remains after subtracting the beer and wine servings from the total, so the remainder absorbs any rounding drift. Purchase units follow: **beer units** (`beer_units`) are the beer servings divided by 1 serving per unit, rounded up; **wine bottles** (`wine_bottles`) are the wine servings divided by 5 servings per bottle, rounded up; **spirit bottles** (`spirit_bottles`) are the spirit servings divided by 16 servings per bottle, rounded up. Separately, **ice** (`ice_lbs`) is the `guest_count` multiplied by 1.5 pounds per guest, rounded up, and **glassware needed** (`glassware_needed`) is the `guest_count` multiplied by 2.5 glasses per guest, rounded up.

A `Client` may add menu items and signature drinks to an event. A menu item carries a `name`, a `drink_type` (one of `BEER`, `WINE`, `COCKTAIL`, or `MOCKTAIL`), a `spirit_base` for cocktails (one of `VODKA`, `GIN`, `WHISKEY`, `RUM`, `TEQUILA`, or `NONE`, defaulting to `NONE` for non-cocktails), an `is_signature` flag defaulting to false, and an `abv_pct` alcohol-by-volume percentage of at least 0. It references its event via `event_id`.

### 3.7. Running the Event

Once compliance is cleared and the deposit is in hand, the `Client` confirms the event, advancing `booking_status` `DRAFT → CONFIRMED`. Confirmation is gated twice: the `compliance_posture` must be `CLEARED`, else `ERR_COMPLIANCE_NOT_CLEARED` (HTTP 409); and the `payment_status` must be `DEPOSIT_PAID` or `PAID_IN_FULL`, else `ERR_DEPOSIT_NOT_PAID` (HTTP 409).

A `Coordinator` starts service, advancing `CONFIRMED → IN_PROGRESS`, but only when at least one child assignment in the `LEAD` role has reached `CHECKED_IN`. If no lead has checked in, the start is rejected with `ERR_NO_CHECKED_IN_STAFF` (HTTP 409) — the empty checked-in set is explicitly a rejection. The coordinator later completes service, advancing `IN_PROGRESS → COMPLETED`; completion cascades every child assignment still in `CHECKED_IN` to `COMPLETED`, recomputing those bartenders' reliability and decrementing each one's `upcoming_assignment_count`. Finally the coordinator closes the event, advancing `COMPLETED → CLOSED`, but only once every kit reservation for the event is either `RETURNED` or `RELEASED` and every breakage report for the event is `SETTLED`, else the close is rejected with `ERR_INVALID_STATE` (HTTP 409). `CLOSED` and `CANCELLED` are the terminal booking states.

### 3.8. Cancellation and Its Cascades

A `Client` may cancel an event while it is `DRAFT` or `CONFIRMED`, moving `booking_status` to `CANCELLED` and setting `cancelled_by` to `CLIENT`. The financial consequences depend on where the money stands. Cancelling a `DRAFT` event that is still `UNPAID` incurs no cancellation fee. If a deposit had already been paid — the case for a `CONFIRMED` cancellation, or a `DRAFT` cancellation after a deposit — the deposit cascade fires: the system creates a `CANCELLATION_FEE` payment equal to the current `amount_paid_cents` multiplied by 50 percent (rounded), and a `REFUND` payment equal to `amount_paid_cents` less that cancellation fee. Money is conserved — the amounts paid in, minus the refund, equal the cancellation fee. The event's `payment_status` is then recomputed to `SETTLED`, its `balance_due_cents` reconciled to 0, and `amount_paid_cents` reflects the refund.

Cancelling a confirmed event also un-staffs it. Every child assignment in `PROPOSED` or `CONFIRMED` is driven to `CANCELLED` with `cancelled_by` set to `SYSTEM`; each such cancellation decrements that bartender's `upcoming_assignment_count` by 1 and recomputes the bartender's reliability scores.

### 3.9. Breakage Reconciliation

After a kit comes back, a `Coordinator` files a breakage report to reconcile the glassware. The filing supplies the `kit_id`, an `items_broken` count (at least 0), and an `items_returned` count (at least 0), and references the event via `event_id`. A report can only be filed when a kit reservation for that `event_id` and `kit_id` pairing has reached `RETURNED`; without a returned reservation the filing is rejected with `ERR_KIT_NOT_RETURNED` (HTTP 409). On creation the report copies the returned reservation's `items_checked_out` as its own conservation baseline and opens with `status` of `DRAFT`. Glassware must conserve: `items_broken` plus `items_returned` must equal that `items_checked_out` baseline, else the filing is rejected with `ERR_BREAKAGE_COUNT_MISMATCH` (HTTP 422).

Settling the report, driven by a coordinator, advances `DRAFT → SETTLED` and computes the charge. A **free-breakage allowance** is the `items_checked_out` baseline multiplied by 2 percent, rounded up. The **chargeable broken** count is the amount by which `items_broken` exceeds that allowance, or zero if it does not exceed it. The **breakage fee** (`breakage_fee_cents`) is the chargeable broken count multiplied by 500 cents of replacement cost per item. An informational **deposit refund** figure (`deposit_refund_cents`) is the event's `deposit_due_cents` less the breakage fee, floored at 0. When the breakage fee is greater than 0, settling creates a `BREAKAGE_CHARGE` payment equal to the fee; that new charge then flows back through the ledger, recomputing the event's `balance_due_cents` and `payment_status`.

## 4. Endpoint Definitions

New resource creation returns HTTP 201; reads and state-changing operations that modify an existing resource return HTTP 200. All error responses use the envelope and codes of §2.2 and §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/packages` | Create a beverage-catering package tier | PlatformAdmin |
| POST | `/bartenders` | Register a bartender in the staffing pool | PlatformAdmin |
| GET | `/bartenders/{id}` | Read a bartender including computed reliability scores | PlatformAdmin, Coordinator, Bartender |
| POST | `/bartenders/{id}/deactivate` | Retire a bartender from the bookable pool | PlatformAdmin |
| POST | `/bar-kits` | Add a mobile bar equipment kit to the fleet | PlatformAdmin |
| POST | `/clients` | Register a client/host | PlatformAdmin |
| POST | `/events` | Book a new event in DRAFT and compute provisional pricing, deposit and staffing | Client |
| GET | `/events` | List events, optionally filtered by `client_id`, `package_id`, or `booking_status` (a `Client` caller additionally sees only events it owns) | PlatformAdmin, Coordinator, ComplianceOfficer, Client |
| GET | `/events/{id}` | Read one event with computed financial and posture fields | PlatformAdmin, Coordinator, ComplianceOfficer, Client |
| PATCH | `/events/{id}` | Edit event guest count / schedule / venue type (OCC-guarded) | Client |
| POST | `/events/{id}/confirm` | Confirm a DRAFT event | Client |
| POST | `/events/{id}/cancel` | Cancel an event and run refund/assignment cascades | Client |
| POST | `/events/{id}/start` | Start service (requires a checked-in LEAD) | Coordinator |
| POST | `/events/{id}/complete` | Complete service; cascade checked-in assignments to COMPLETED | Coordinator |
| POST | `/events/{id}/close` | Archive a completed event once kits returned and breakage settled | Coordinator |
| POST | `/events/{id}/payments` | Record a client DEPOSIT or BALANCE payment | Client |
| GET | `/events/{id}/payments` | List all payment records for an event | PlatformAdmin, Coordinator, Client |
| POST | `/events/{id}/compliance-review` | Open a compliance review (DRAFT) for the event | Coordinator |
| GET | `/events/{id}/compliance-review` | List the event's compliance review(s) | PlatformAdmin, Coordinator, ComplianceOfficer, Client |
| POST | `/compliance-reviews/{id}/submit` | Submit or resubmit a review for officer sign-off | Coordinator |
| POST | `/compliance-reviews/{id}/clear` | Officer clears compliance | ComplianceOfficer |
| POST | `/compliance-reviews/{id}/request-changes` | Officer rejects compliance; runs block/revert cascade | ComplianceOfficer |
| POST | `/events/{id}/assignments` | Schedule a bartender for the event (OCC-guarded) | Coordinator |
| GET | `/assignments` | List assignments filtered by `bartender_id`, `event_id`, or `status` | PlatformAdmin, Coordinator, Bartender |
| GET | `/assignments/{id}` | Read one assignment | PlatformAdmin, Coordinator, Bartender |
| POST | `/assignments/{id}/confirm` | Confirm a proposed assignment | Coordinator |
| POST | `/assignments/{id}/check-in` | Bartender checks in on the day of service | Bartender |
| POST | `/assignments/{id}/cancel` | Cancel a proposed/confirmed assignment | Coordinator, Bartender |
| POST | `/assignments/{id}/no-show` | Mark a confirmed bartender a no-show | Coordinator |
| POST | `/events/{id}/kit-reservations` | Reserve a bar kit for the event's window | Coordinator |
| GET | `/kit-reservations` | List kit reservations filtered by `kit_id`, `event_id`, or `status` | PlatformAdmin, Coordinator |
| GET | `/kit-reservations/{id}` | Read one kit reservation | PlatformAdmin, Coordinator |
| POST | `/kit-reservations/{id}/deploy` | Deploy the kit; snapshot glassware as items_checked_out | Coordinator |
| POST | `/kit-reservations/{id}/return` | Return the deployed kit | Coordinator |
| POST | `/kit-reservations/{id}/release` | Release a reserved (not yet deployed) kit | Coordinator |
| POST | `/events/{id}/inventory-plan` | Generate (or regenerate a STALE) BYOB inventory plan | Coordinator |
| GET | `/events/{id}/inventory-plan` | List the event's inventory plan | PlatformAdmin, Coordinator, Client |
| POST | `/events/{id}/menu-items` | Add a menu item / signature drink to the event | Client |
| GET | `/events/{id}/menu-items` | List the event's menu items | PlatformAdmin, Coordinator, Client |
| POST | `/events/{id}/breakage-reports` | File a glassware breakage/return reconciliation | Coordinator |
| GET | `/breakage-reports` | List breakage reports filtered by kit or event | PlatformAdmin, Coordinator |
| GET | `/breakage-reports/{id}` | Read one breakage report | PlatformAdmin, Coordinator |
| POST | `/breakage-reports/{id}/settle` | Settle the breakage report; compute fee and charge client | Coordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 400 |
| ERR_CLIENT_NOT_FOUND | 404 |
| ERR_PACKAGE_NOT_FOUND | 404 |
| ERR_BARTENDER_NOT_FOUND | 404 |
| ERR_BARKIT_NOT_FOUND | 404 |
| ERR_EVENT_NOT_FOUND | 404 |
| ERR_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_COMPLIANCE_REVIEW_NOT_FOUND | 404 |
| ERR_KIT_RESERVATION_NOT_FOUND | 404 |
| ERR_BREAKAGE_REPORT_NOT_FOUND | 404 |
| ERR_STALE_EVENT_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_ABC_MODEL_INVALID | 422 |
| ERR_INSURANCE_NOT_VERIFIED | 422 |
| ERR_HOST_ATTESTATION_MISSING | 422 |
| ERR_COMPLIANCE_NOT_CLEARED | 409 |
| ERR_BARTENDER_CERT_EXPIRED | 422 |
| ERR_JURISDICTION_MISMATCH | 422 |
| ERR_BARTENDER_UNAVAILABLE | 409 |
| ERR_BARTENDER_DOUBLE_BOOKED | 409 |
| ERR_KIT_DOUBLE_BOOKED | 409 |
| ERR_INSUFFICIENT_RELIABILITY | 422 |
| ERR_NO_CHECKED_IN_STAFF | 409 |
| ERR_KIT_NOT_RETURNED | 409 |
| ERR_BREAKAGE_COUNT_MISMATCH | 422 |
| ERR_DEPOSIT_NOT_PAID | 409 |
| ERR_PAYMENT_EXCEEDS_BALANCE | 422 |
