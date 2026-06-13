# Uniform & Workwear Rental Program API — Product Requirements Document

## 1. Introduction

This document specifies the Uniform & Workwear Rental Program API, the operational backbone of a managed-garment rental service in the style of an industrial uniform provider. The business rents physical work garments to customer accounts, fits them to named employees on a sizing roster, and cycles those garments through a weekly pickup-clean-deliver rotation that keeps each wearer stocked with clean uniforms. Around that core rotation the program layers a full commercial apparatus: catalog pricing, soil-count reconciliation with shortage tolerances, embroidered emblem setup, loss and damage recovery fees, route scheduling with delivery windows, and a per-account billing ledger that can place a delinquent customer on hold.

The system serves four distinct operator populations whose work interlocks but rarely overlaps: a customer-facing account manager who curates the wearer roster and assigns garments, a field driver who runs the physical pickup and delivery at each route stop, a plant cleanroom technician who advances soiled garments through the wash, and a program administrator who owns the catalog, the routes, and the billing overrides. Because money flows from physical events — a garment scanned into soil, a wash cycle completed, a uniform declared lost — the API must reconcile an estimated weekly charge raised at delivery time against a finalized charge computed once an administrator closes the books on the visit. The requirements below define every entity, state transition, calculation, validation, and access rule needed to keep those estimates and finalizations consistent, and to keep each account's outstanding balance an accurate reflection of the physical reality on the route.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting operator, and `X-User-Role` declares the operational capacity under which the request is made. If `X-User-Role` is missing or does not name one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED`. If the header is valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles, spelled as follows: `ProgramAdmin`, `AccountManager`, `RouteDriver`, and `CleanroomTech`. A `ProgramAdmin` manages the garment-type catalog, wash stations, routes, account creation, billing overrides, and visit reconciliation. An `AccountManager` curates a customer's wearer roster and drives garment assignment, return, loss, and damage actions. A `RouteDriver` runs pickup and delivery in the field. A `CleanroomTech` advances garments through the plant wash cycle.

All four roles carry an **opaque** identity. When `X-User-Role` is `ProgramAdmin`, `AccountManager`, `RouteDriver`, or `CleanroomTech`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity in the system. The server may record such an identifier where the data model calls for it — for example, a route's responsible driver is captured in the `driver_user_id` field on the route — but the server never compares `X-User-ID` to any entity's `id`, and ownership of a resource is never inferred from the caller's identity. Authorization is therefore purely role-based: any operator presenting a permitted role may act on any resource the role is allowed to touch.

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

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside these bounds is rejected with `ERR_PAGINATION_INVALID`.

Unless a specific endpoint states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the count of all matching resources before the page window is applied and `has_more` indicates whether further items remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. Resources that may be modified after creation additionally carry an `updated_at` timestamp (same ISO 8601 UTC format) that is refreshed on every mutation, and an integer `version` that begins at its initial value of 1 on creation and increments by exactly one on every mutation. The `version` field underpins optimistic concurrency control as described in §2.7.

In this program every primary entity — `Account`, `Wearer`, `GarmentType`, `Garment`, `WashStation`, `Assignment`, `Route`, `RouteStop`, `ServiceVisit`, and `ServiceCharge` — is mutable and therefore exposes the full set: `id`, `created_at`, `updated_at`, and `version`. There are no create-only immutable entities in this domain; each entity listed above carries `updated_at` and `version`.

### 2.5. Hierarchical Consistency and Cascading Effects

Several operations in this system mutate more than one entity in a single request, and the requirements throughout §3 name each cascade explicitly. The general principle is that a physical or financial event recorded against one resource propagates immediately and synchronously to every derived value it influences, and each entity touched during a cascade has its own `updated_at` refreshed and its own `version` incremented by one.

The financial nerve of the system is the account ledger. Two account fields are derived rather than directly written: `outstanding_cents` is the running total of unpaid charges, and `billing_status` is the posture computed from that total. Whenever a charge is created (at delivery, at reconciliation, on a declared loss, or on a declared damage) or settled, the owning account's `outstanding_cents` and `billing_status` are recomputed before the request returns. This recompute of an account's derived fields (`outstanding_cents`, `active_wearer_count`, and the automatic `billing_status` posture) refreshes the account's `updated_at` and increments its `version` only when one of those tracked values actually changes; a recompute that leaves all three unchanged is a no-op that neither touches `updated_at` nor bumps `version`. The wearer roster carries its own derived counters: `assigned_garment_count` on a wearer and `active_wearer_count` on an account both reflect live state and are recomputed as garments are assigned or returned and as wearers move through their roster lifecycle.

### 2.6. Nested Resource Retrieval and Path Validation

Many endpoints address a resource nested beneath a parent in the URL path — for example a wearer or garment beneath an account, a stop beneath a route, or a visit beneath a route stop. For any such request, the system validates each path identifier in left-to-right order and rejects the request with `ERR_RESOURCE_NOT_FOUND` the moment the first identifier in the path fails to resolve to an existing resource. A request for a service visit under a non-existent route stop, for instance, fails on the route stop before the visit is ever looked up. This existence check (validation priority 3) precedes every business rule: a malformed or absent parent is reported before the system evaluates state, referential, or constraint conditions on the child.

### 2.7. Optimistic Concurrency Control on Reconciliation

Reconciling a service visit is the one operation in this system that is guarded by optimistic concurrency control. When an administrator reconciles a visit, the request body must carry `expected_service_visit_version`, which is required and not optional; it must hold the `version` of the target `ServiceVisit` that the client last observed. The server compares that value to the visit's current `version`. If they differ — that is, if another writer has advanced the visit's `version` since the client read it — the reconciliation is rejected with `ERR_STALE_VISIT_VERSION` and HTTP status 412.

This guard exists because reconciliation legitimately supersedes the provisional charges raised at delivery: it deletes the provisional charge rows and writes finalized ones. Were a stale-view writer allowed to reconcile a visit that another administrator had already reconciled, the finalized charges would be applied twice and the account ledger would drift. The version check prevents that double application by ensuring a client only reconciles a visit it has actually observed in its current form. No other endpoint in the system accepts a version field, and no other endpoint performs a version check; reconciliation is the sole optimistic-concurrency-controlled write.

### 2.8. Monetary Precision and the Soil-Count Grace Tolerance

Every monetary value in this system is expressed and stored as an **integer number of cents** — `weekly_rate_cents`, `replacement_cost_cents`, `emblem_setup_cents`, `amount_cents`, `outstanding_cents`, `provisional_charge_cents`, and `finalized_charge_cents` are all whole-cent integers. Rental and shortage arithmetic involves only integer cents and therefore requires no rounding. The single place rounding enters is the damage-fee calculation, where a percentage of a replacement cost is taken and the result is floored to a whole number of cents (see §3.6); the floor is applied after the multiplication, never before.

Soil reconciliation operates on a per-account grace tolerance. Each account declares `shortage_grace_units`, an integer of at least zero that defaults to 2 when not supplied at account creation. This is the number of garments by which a single visit's soil scan may fall short of expectation before any shortage charge applies; it is consumed by both the provisional and finalized charge calculations as the tolerance subtracted before billing for missing garments.

### 2.9. Validation Ordering

When several validation conditions could apply to a single request, they are evaluated in a fixed priority order so that the first failing condition determines the error returned. The order is: (1) authentication — a present, declared `X-User-Role`, else `ERR_UNAUTHENTICATED`; (2) authorization — the acting role is permitted for the operation, else `ERR_FORBIDDEN_ROLE`; (3) path existence — every path identifier resolves left-to-right, else `ERR_RESOURCE_NOT_FOUND`; (4) referential integrity of body foreign keys, else `ERR_FK_INTEGRITY`; (5) state legality of the requested transition, else `ERR_INVALID_STATE`; (6) the account-on-hold safety gate, else `ERR_ACCOUNT_ON_HOLD`; (7) wearer-active constraint on assignment, else `ERR_WEARER_NOT_ACTIVE`; (8) the wearer-has-garments removal constraint, else `ERR_WEARER_HAS_GARMENTS`; (9) route-stop window overlap, else `ERR_STOP_WINDOW_OVERLAP`; (10) wash-station capacity, else `ERR_WASH_STATION_FULL`; (11) stop-sequence buffering, else `ERR_STOP_SEQUENCE_CONFLICT`; (12) uniqueness of natural keys, else `ERR_DUPLICATE_KEY`; (13) reconciliation version match, else `ERR_STALE_VISIT_VERSION`; and (14) general body well-formedness, else `ERR_INVALID_REQUEST`. Authentication therefore always surfaces before authorization, existence before any business rule, and a structural body problem is reported only once the request has cleared the higher-priority gates that share its endpoint.

## 3. Business Logic & Workflows

### 3.1. Onboarding an Account and Its Billing Posture

The customer relationship begins when a program administrator opens an `Account` by supplying the customer's `legal_name`, a weekly `service_day` drawn from the set `MON`, `TUE`, `WED`, `THU`, or `FRI`, and optionally the `shortage_grace_units` tolerance. A freshly opened account starts life in a `CURRENT` billing posture, with its `outstanding_cents` ledger at zero and its `active_wearer_count` at zero. The account's `billing_status` is one of `CURRENT`, `PAST_DUE`, or `ON_HOLD`, and the account also exposes its derived `outstanding_cents` and `active_wearer_count` when fetched.

An account's posture tracks its debt automatically. After any charge is created or settled, the system recomputes the account's outstanding total and re-evaluates the posture. The crossing into `PAST_DUE` is strict: an account moves from `CURRENT` to `PAST_DUE` only when its `outstanding_cents` rises strictly above 500 dollars (that is, above 50,000 cents — equality at exactly that figure does not trip the threshold). The reverse system transition from `PAST_DUE` back to `CURRENT` occurs after a settlement leaves the outstanding total at or below that same 50,000-cent line.

Beyond the automatic postures, an administrator may intervene manually. A `PAST_DUE` account can be placed on hold, moving its `billing_status` from `PAST_DUE` to `ON_HOLD`; this is permitted only while the account is `PAST_DUE`. Releasing a hold moves the posture from `ON_HOLD` back to `CURRENT`, and is permitted only while the account is `ON_HOLD` and its `outstanding_cents` stands at or below 50,000 cents. An attempt to drive either posture transition from a state where it is not defined is rejected with `ERR_INVALID_STATE`. The `ON_HOLD` posture is consequential: it freezes any operation that would grow the account's garment footprint, as described in §3.2.

### 3.2. Building the Wearer Roster and Its Ramp Lifecycle

An account manager populates the roster by adding a `Wearer` to an account, providing the employee's `full_name`, a `shirt_size` from the set `XS`, `S`, `M`, `L`, `XL`, or `XXL`, a numeric `pant_size` that is an integer waist measurement between 28 and 48 inclusive, and a `locker_label` naming the physical locker slot where the wearer's clean garments are racked at the stop. The wearer's `account_id` ties it to its account. Each wearer's `locker_label` must be unique among the account's wearers that have not been removed — that is, unique across the account's `ACTIVE` and `RAMP_DOWN` wearers — and a collision is rejected with `ERR_DUPLICATE_KEY`. A new wearer enters in `ACTIVE` roster status, and the account's `active_wearer_count` is recomputed to include it.

A wearer's `roster_status` is one of `ACTIVE`, `RAMP_DOWN`, or `REMOVED`, and the wearer also carries a derived `assigned_garment_count` reflecting how many garments are currently assigned to it. The roster lifecycle is a branching machine with a revert edge. Ramping a wearer down moves `roster_status` from `ACTIVE` to `RAMP_DOWN`; this freezes new garment assignments to that wearer while leaving existing garments billable until they are returned. Reinstating a ramped-down wearer is the revert edge, moving `roster_status` from `RAMP_DOWN` back to `ACTIVE`. Both ramp-down and reinstatement are footprint-affecting operations and are blocked when the account is `ON_HOLD`: attempting either on an `ON_HOLD` account is rejected with `ERR_ACCOUNT_ON_HOLD`. Removing a wearer is the terminal step, moving `roster_status` from `RAMP_DOWN` to `REMOVED` and recomputing the account's `active_wearer_count`; it is permitted only from `RAMP_DOWN`.

Removal carries one further guard. A wearer can be removed only once every garment has left its hands — that is, only while its `assigned_garment_count` is exactly zero. A removal attempt against a wearer still holding one or more assigned garments is rejected with `ERR_WEARER_HAS_GARMENTS`. Any of these roster transitions attempted from a state where the transition is not defined — ramping down a wearer that is not `ACTIVE`, reinstating one that is not `RAMP_DOWN`, or removing one that is not `RAMP_DOWN` — is rejected with `ERR_INVALID_STATE`.

### 3.3. Cataloging Garment Types, Stations, and Physical Garments

The catalog is administrator territory. A `GarmentType` is created with a globally unique `sku`, a `category` of `SHIRT`, `PANT`, `JACKET`, or `COVERALL`, a per-garment weekly rental rate in `weekly_rate_cents`, a full `replacement_cost_cents` used when a garment is lost, and a one-time `emblem_setup_cents` charged the first time an emblem is embroidered onto a garment of that type. Each of `weekly_rate_cents`, `replacement_cost_cents`, and `emblem_setup_cents` must be at least zero. A wash station is created with a globally unique `station_code` and an integer `capacity` of at least one, the latter being the maximum number of garments whose wash slots may overlap at any single instant on that station. A duplicate `sku` or `station_code` is rejected with `ERR_DUPLICATE_KEY`.

A physical `Garment` is provisioned into a specific account's pool by an administrator, who supplies the `garment_type_id` of the catalog style, a `tag_code` carrying the barcode or RFID identifier on the physical item, and optionally an `emblem_text` if the garment ships pre-embroidered. When `emblem_text` is omitted it defaults to null, and a provided-but-blank (empty or whitespace-only) `emblem_text` at provisioning is rejected with `ERR_INVALID_REQUEST`. The garment's `account_id` records the renting account. The `tag_code` must be unique within that account, and a collision is rejected with `ERR_DUPLICATE_KEY`. A garment carries two **independent** state dimensions that evolve separately. The first is its inventory `lifecycle_status`, one of `IN_STOCK`, `ASSIGNED`, `RETIRED`, or `LOST`, which begins at `IN_STOCK`. The second is its `wash_location`, one of `AT_PLANT`, `AT_CUSTOMER`, `IN_SOIL`, or `IN_WASH`, which begins at `AT_PLANT`. On provisioning, a garment's `soil_strikes` counter starts at zero.

A garment exposes several further derived fields that the wash cycle and reconciliation depend upon. Its `soil_strikes` counts the visits at which the garment was expected back in soil but was kept by the wearer instead, and this counter drives the damage-fee escalation tiers. Its `cycled_through_wash_this_visit` boolean records whether the garment has completed a full plant wash cycle since the current visit's pickup; it is reset to false at each pickup and set true when the garment finishes washing, and it gates which garments are billable in the finalized charge. While a garment is in the wash, its `wash_station_id` names the occupied station and its `slot_start_min` and `slot_end_min` record the reserved slot window in minutes from midnight; all three are null when the garment is not `IN_WASH`. When present, the slot window must satisfy a start of at least zero, a start strictly less than the end, and an end of at most 1440.

### 3.4. The Assignment Junction: Fitting Garments to Wearers

Garments reach wearers through an `Assignment`, the junction an account manager creates by supplying the `garment_id` and the `wearer_id`. The assignment's `account_id` is copied from the garment rather than supplied by the caller, and its `assigned_at_iso` records the moment of assignment. An assignment's `status` is one of `ASSIGNED`, `RETURNED`, `LOST`, or `DAMAGED`, beginning at `ASSIGNED`; its `closed_at_iso` is null while `ASSIGNED` and is stamped with the closing time when the assignment reaches any terminal status.

Creating an assignment is the footprint-growing operation par excellence and is gated on several conditions. The garment and wearer named in the body must both exist and, critically, must belong to the same account, since a garment is assigned within the account that rents it; a body foreign key that does not resolve, or a garment and wearer drawn from different accounts, is rejected with `ERR_FK_INTEGRITY`. The garment must be assignable: its `lifecycle_status` must be `IN_STOCK` and its `wash_location` must be `AT_PLANT`, otherwise the transition is undefined and rejected with `ERR_INVALID_STATE`. The account must not be `ON_HOLD`, else `ERR_ACCOUNT_ON_HOLD`. And only an `ACTIVE` wearer may receive a garment: assigning to a wearer whose `roster_status` is `RAMP_DOWN` or `REMOVED` is rejected with `ERR_WEARER_NOT_ACTIVE`. When all gates pass, the assignment is created in `ASSIGNED` status, the garment's `lifecycle_status` advances `IN_STOCK → ASSIGNED` while its `wash_location` simultaneously advances `AT_PLANT → AT_CUSTOMER`, the wearer's `assigned_garment_count` increments by one, and the garment's `version` increments by one.

The assignment branches into three terminal outcomes, all driven by the account manager and all requiring the assignment to currently be `ASSIGNED` with its linked garment also `ASSIGNED` (otherwise `ERR_INVALID_STATE`). **Returning** a garment moves the assignment `ASSIGNED → RETURNED`, stamps `closed_at_iso`, drives the garment back `ASSIGNED → IN_STOCK` (and its `wash_location` back to `AT_PLANT`), decrements the wearer's `assigned_garment_count` by one, and increments the assignment's `version`. **Declaring a loss** moves the assignment `ASSIGNED → LOST`, stamps `closed_at_iso`, drives the garment's `lifecycle_status` to `LOST`, creates a `LOSS` `ServiceCharge` against the visit's account computed by the loss-and-damage fee rule (cascade hop one), then recomputes the account's `outstanding_cents` and `billing_status` (cascade hop two), decrements the wearer's `assigned_garment_count` by one, and increments the assignment's `version`. **Declaring damage** moves the assignment `ASSIGNED → DAMAGED`, stamps `closed_at_iso`, drives the garment's `lifecycle_status` to `RETIRED`, creates a `DAMAGE` `ServiceCharge` by the same fee rule (cascade hop one), recomputes the account ledger (cascade hop two), decrements the wearer's `assigned_garment_count` by one, and increments the assignment's `version`. Each of these three outcomes carries equal weight in the ledger: loss and damage both raise a charge and both cascade into the account posture, while a plain return raises no charge.

### 3.5. Emblems, Retirement, and the Wash Cycle

Embroidery is applied through an apply-emblem capability available to both administrators and account managers, which takes a new `emblem_text` and writes it onto the garment. The text must not be blank; an empty or whitespace-only `emblem_text`, as well as a missing or null `emblem_text`, is rejected with `ERR_EMBLEM_TEXT_INVALID`. The financial consequence depends on the garment's history: the **first** emblem ever applied to a garment — the boundary where `emblem_text` transitions from null to a non-null value — incurs the garment type's one-time `emblem_setup_cents` as an `EMBLEM_SETUP` `ServiceCharge`, whereas re-applying or changing the text on a garment that already carries an emblem charges nothing because the setup has already been amortized. Applying an emblem increments the garment's `version`.

Retirement is a separate administrator action. A garment may be retired when its `lifecycle_status` is `ASSIGNED` or `IN_STOCK`, and only when the garment has accumulated enough soil strikes to warrant it — concretely, when its `soil_strikes` is at least 4; the retire endpoint carries no request body and recognizes no separate "damage return" override, so a retire attempt against a garment whose `soil_strikes` is below 4 (or whose `lifecycle_status` is neither `ASSIGNED` nor `IN_STOCK`) is rejected with `ERR_INVALID_STATE`. Retirement sets `lifecycle_status` to `RETIRED`, and if the garment's linked assignment is still `ASSIGNED`, a `DAMAGE` `ServiceCharge` is raised by the loss-and-damage fee rule (which then recomputes the account ledger); the garment's `version` increments. Both `RETIRED` and `LOST` are terminal lifecycle states.

The wash dimension turns independently of the lifecycle dimension — a garment stays `ASSIGNED` throughout the week while its `wash_location` cycles `AT_CUSTOMER → IN_SOIL → IN_WASH → AT_PLANT → AT_CUSTOMER`. A cleanroom technician advances a soiled garment by starting a wash, which is permitted only while the garment's `wash_location` is `IN_SOIL`. Starting a wash requires a body naming the `wash_station_id` along with the `slot_start_min` and `slot_end_min` of the reserved slot; the referenced station must exist (else `ERR_FK_INTEGRITY`) and the slot window must be well-formed with a start of at least zero, a start strictly below the end, and an end of at most 1440. The garment's `wash_location` advances `IN_SOIL → IN_WASH`, its `wash_station_id` and slot window are recorded from the body, and its `version` increments. Finishing a wash is permitted only while `wash_location` is `IN_WASH`; it advances the garment `IN_WASH → AT_PLANT`, clears `wash_station_id`, `slot_start_min`, and `slot_end_min` back to null, sets `cycled_through_wash_this_visit` to true, and increments `version`. A start-wash or finish-wash attempted from the wrong `wash_location` is rejected with `ERR_INVALID_STATE`.

Wash stations enforce an aggregate-capacity rule with interval semantics distinct from the route-stop rule below. A new garment's slot `[slot_start_min, slot_end_min)` may be admitted to a station only if, at no instant within that interval, more than the station's `capacity` garment slots overlap on that station — counting the new garment in the tally. Many slots may overlap freely up to the capacity figure; it is the slot that would become the capacity-plus-one-th simultaneously active slot at some instant that is rejected, with `ERR_WASH_STATION_FULL`.

### 3.6. Loss and Damage Fees

When a garment is declared lost, the fee is simply the full `replacement_cost_cents` of the garment's type, with no tiering. When a garment is declared damaged — whether through a damage declaration on its assignment or through a retire-for-damage action — the fee is a tiered fraction of that replacement cost, and the order of evaluation is fixed: the system first selects the tier multiplier from the garment's accumulated `soil_strikes`, then multiplies the replacement cost by that multiplier, then floors the product to a whole number of cents, and finally clamps the result so it can never exceed the full replacement cost (a damaged garment never costs more than a lost one).

The tier is chosen by threshold against `soil_strikes`. If the garment's `soil_strikes` is at least 4, the multiplier is 0.75. Otherwise, if its `soil_strikes` is at least 2, the multiplier is 0.50. Otherwise — fewer than two strikes — the multiplier is 0.25. The raw fee is the floor of the replacement cost multiplied by the chosen fraction, and the final damage fee is the smaller of that raw figure and the full replacement cost. Whichever fee results — loss or damage — is recorded on a `ServiceCharge` whose `charge_type` is `LOSS` or `DAMAGE` accordingly, and that charge's creation cascades into the account's `outstanding_cents` and `billing_status` recomputation.

### 3.7. Routes, Stops, and the Two Interval Geometries

A `Route` is an administrator-created delivery circuit identified by a globally unique `route_code`, a `service_day` weekday from `MON`, `TUE`, `WED`, `THU`, or `FRI`, and a `driver_user_id` naming the opaque driver operator responsible for it. A duplicate `route_code` is rejected with `ERR_DUPLICATE_KEY`. Onto a route an administrator threads `RouteStop` rows, each supplying the `route_id` it belongs to, the `account_id` serviced at the stop, a `stop_sequence` giving the visiting order, and a delivery window expressed as `window_start_min` (inclusive) and `window_end_min` (exclusive) in minutes from midnight. The window must be well-formed: a start of at least zero, a start strictly below the end, and an end of at most 1440, else `ERR_INVALID_REQUEST`.

Two distinct interval rules govern stops on the same route, and they are not the same geometry. The **window-overlap** rule forbids any positive-length intersection between a new stop's `[window_start_min, window_end_min)` and the window of any existing stop on the same route; because the windows are half-open, two windows that merely touch at a single endpoint (one stop's end equal to the next stop's start) do **not** conflict, while any overlap of positive length does. A violation is rejected with `ERR_STOP_WINDOW_OVERLAP`. The **sequence** rule is stronger than mere non-overlap and concerns the order of service. Each `stop_sequence` value must be unique within the route, and consecutive sequence-ordered stops must respect a fixed fifteen-minute travel buffer: a later stop's `window_start_min` must be at least the immediately-prior sequence's `window_end_min` plus fifteen minutes. A duplicated `stop_sequence`, or a buffer the new stop fails to honor, is rejected with `ERR_STOP_SEQUENCE_CONFLICT`.

### 3.8. The Weekly Service Visit: Pickup

The rotation is realized as a `ServiceVisit`, a cyclic weekly record scheduled against a route stop by an administrator or a driver. A visit is created with a `week_index`, a monotonic week counter that must be a non-negative integer and that uniquely identifies the visit within its stop; the visit's `route_stop_id` records the stop, and its `account_id` is copied from that stop at creation. A visit's `status` cycles through `SCHEDULED`, `PICKED_UP`, `DELIVERED`, and `RECONCILED`, beginning at `SCHEDULED`, with `RECONCILED` terminal. A visit also exposes the derived `expected_soil_count`, the driver-supplied `actual_soil_count`, and the two charge totals `provisional_charge_cents` and `finalized_charge_cents`, the latter of which stays at zero until reconciliation.

Pickup is the driver's first field action and is permitted only while the visit is `SCHEDULED`, else `ERR_INVALID_STATE`. The driver submits `actual_soil_count`, the number of garments actually scanned into soil, which must be a non-negative integer; a negative value is rejected with `ERR_SOIL_COUNT_NEGATIVE`. On pickup the system snapshots `expected_soil_count` as the count of the account's garments that are currently `ASSIGNED` and `AT_CUSTOMER` — the garments that ought to be coming back. A submitted `actual_soil_count` exceeding that snapshot `expected_soil_count` is rejected as `ERR_INVALID_REQUEST`, since the driver cannot scan back more garments than were out. For every `ASSIGNED` garment on the account, `cycled_through_wash_this_visit` is reset to false at this pickup. The system then moves exactly the smaller of `actual_soil_count` and `expected_soil_count` garments from `AT_CUSTOMER` into `IN_SOIL`, choosing the oldest first — ordered by `assigned_at_iso` ascending and then by `created_at` ascending. The garments left behind — the difference between `expected_soil_count` and `actual_soil_count`, representing uniforms the wearer kept — each have their `soil_strikes` incremented by one (the first cascade hop of the pickup). Finally the visit advances `SCHEDULED → PICKED_UP` and its `version` increments by one.

### 3.9. Delivery and the Provisional Charge

Delivery is the driver's second action, advancing the visit `PICKED_UP → DELIVERED`, and it is permitted only while the visit is `PICKED_UP`. Delivery additionally requires that the plant work be finished: every garment for this account must have completed its journey out of soil and wash, meaning no garment for the account may remain `IN_SOIL` or `IN_WASH`. If any garment is still soiled or still washing, delivery is rejected with `ERR_VISIT_GARMENTS_NOT_CLEAN`; an attempt from a non-`PICKED_UP` status is instead `ERR_INVALID_STATE`. On a clean delivery, each `ASSIGNED` garment sitting `AT_PLANT` for the account has its `wash_location` set back to `AT_CUSTOMER`, completing the cycle.

Delivery then computes the **provisional** weekly charge and writes it to `provisional_charge_cents`. The provisional variant deliberately bills optimistically from the pickup scan alone. Its rental portion is the sum, over every garment of the account whose `lifecycle_status` is `ASSIGNED` at delivery time (garments that have been lost or retired are excluded), of that garment's type's `weekly_rate_cents` — the full weekly rate is charged for each assigned garment regardless of whether it actually cycled through the wash. Its shortage portion derives from the pickup soil scan: the shortfall is the larger of zero and the quantity obtained by taking `expected_soil_count`, subtracting `actual_soil_count`, and then subtracting the account's `shortage_grace_units`; the shortage portion is that shortfall multiplied by fifteen dollars per missing garment (1,500 cents per unit). The provisional charge is the rental portion plus the shortage portion, in whole cents with no rounding. Delivery then creates one `ServiceCharge` of `charge_type` `RENTAL` for the rental portion, and — only if the shortage portion is greater than zero — one `ServiceCharge` of `charge_type` `SHORTAGE` for the shortage portion, both with `paid` false. Creating these charges recomputes the account's `outstanding_cents` and `billing_status` (the second cascade hop of delivery), and the visit's `version` increments by one.

### 3.10. Reconciliation and the Finalized Charge

Reconciliation is the administrator's closing act on a visit, advancing it `DELIVERED → RECONCILED`, and it is permitted only while the visit is `DELIVERED` (else `ERR_INVALID_STATE`) and only when the body's `expected_service_visit_version` matches the visit's current `version` — a mismatch yields `ERR_STALE_VISIT_VERSION` at HTTP 412, as detailed in §2.7. A body whose `expected_service_visit_version` is missing, null, or not an integer is rejected (after the state check) with `ERR_INVALID_REQUEST` rather than the stale-version error. Reconciliation computes the **finalized** charge into `finalized_charge_cents` and supersedes the provisional charges: it deletes the provisional `RENTAL` and `SHORTAGE` charge rows for the visit and replaces them with finalized `RENTAL` and `SHORTAGE` rows (with `paid` false), then recomputes the account's `outstanding_cents` and `billing_status`, and increments the visit's `version`. The net account ledger after reconciliation must equal the finalized total — the provisional figures are fully compensated out.

The finalized variant differs from the provisional one in two consequential ways, which is why an identical pickup can finalize to a different total. First, its input set is narrower: the rental portion sums the type `weekly_rate_cents` only over the account's garments that are `ASSIGNED` **and** whose `cycled_through_wash_this_visit` flag is true — that is, only garments that actually completed a full wash cycle this visit are billed rent, whereas the provisional variant billed every assigned garment. Second, the shortage portion grants a good-standing rebate. The reconciled shortfall is computed exactly as the provisional shortfall — the larger of zero and `expected_soil_count` minus `actual_soil_count` minus the account's `shortage_grace_units` — but one additional unit is then forgiven when the account is in good standing: if the account's `billing_status` is `CURRENT`, one is subtracted, and otherwise nothing is forgiven. The billable shortage units are the larger of zero and the reconciled shortfall minus that forgiveness, and the shortage portion is those units multiplied by 1,500 cents each. The finalized charge is the finalized rental portion plus the finalized shortage portion, in whole cents with no rounding.

### 3.11. Settling Charges and the Ledger's Authoritative Total

Every `ServiceCharge` carries a `service_visit_id` linking it to its visit, an `account_id` copied from that visit, a `charge_type` of `RENTAL`, `SHORTAGE`, `LOSS`, `DAMAGE`, or `EMBLEM_SETUP`, an `amount_cents` in whole cents, and a `paid` flag that begins false. Only the visit-driven `RENTAL` and `SHORTAGE` charges raised at delivery and reconciliation carry a non-null `service_visit_id`; the `LOSS`, `DAMAGE`, and `EMBLEM_SETUP` charges, which arise from assignment and emblem actions rather than a visit, are written with `service_visit_id` set to null (and their `account_id` taken from the garment's account). An administrator settles a charge to mark it paid; settling a charge that is already paid is rejected with `ERR_CHARGE_ALREADY_SETTLED`. Settlement sets `paid` to true and recomputes the account ledger.

The account's `outstanding_cents` is the single authoritative derived total, defined as the sum of `amount_cents` across all of the account's charges whose `paid` flag is false. Alongside it, the account's `active_wearer_count` is the count of the account's wearers whose `roster_status` is `ACTIVE`. Both are recomputed whenever the underlying rows change. A settlement that clears enough debt to bring `outstanding_cents` to or below 50,000 cents drives the account's `billing_status` from `PAST_DUE` back to `CURRENT` and increments the account's `version`; conversely, any newly created charge that lifts `outstanding_cents` strictly above 50,000 cents drives `CURRENT` to `PAST_DUE`. This ledger recomputation is the shared tail of every charge-creating event in the system — delivery, reconciliation, declared loss, declared damage, retire-for-damage, and first-emblem setup all converge on it.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code; operations that modify an existing resource — including the state-transition actions and settlement — return a `200 OK` status code. All read operations return `200 OK`. Each endpoint's request body, response shape, and side effects are described in the §3 narratives above; the table below lists only the HTTP surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Create a customer account | ProgramAdmin |
| GET | `/accounts/{id}` | Fetch an account | ProgramAdmin, AccountManager |
| GET | `/accounts` | List accounts (filterable by billing status) | ProgramAdmin, AccountManager |
| POST | `/accounts/{id}/place-hold` | Place a past-due account on hold | ProgramAdmin |
| POST | `/accounts/{id}/release-hold` | Release a held account back to current | ProgramAdmin |
| POST | `/accounts/{id}/wearers` | Add a wearer to an account roster | AccountManager |
| GET | `/accounts/{id}/wearers` | List wearers for an account | ProgramAdmin, AccountManager |
| GET | `/wearers/{id}` | Fetch a wearer | ProgramAdmin, AccountManager |
| POST | `/wearers/{id}/ramp-down` | Ramp a wearer down | AccountManager |
| POST | `/wearers/{id}/reinstate` | Reinstate a ramped-down wearer | AccountManager |
| POST | `/wearers/{id}/remove` | Remove a ramped-down wearer with no garments | AccountManager |
| POST | `/garment-types` | Create a catalog garment type | ProgramAdmin |
| GET | `/garment-types/{id}` | Fetch a garment type | ProgramAdmin, AccountManager, CleanroomTech |
| POST | `/wash-stations` | Create a plant wash station | ProgramAdmin |
| GET | `/wash-stations/{id}` | Fetch a wash station | ProgramAdmin, CleanroomTech |
| GET | `/wash-stations/{id}/garments` | List garments occupying a station's slots | ProgramAdmin, CleanroomTech |
| POST | `/accounts/{id}/garments` | Provision a garment into an account pool | ProgramAdmin |
| GET | `/accounts/{id}/garments` | List garments for an account | ProgramAdmin, AccountManager, CleanroomTech |
| GET | `/garments/{id}` | Fetch a garment | ProgramAdmin, AccountManager, CleanroomTech |
| GET | `/garment-types/{id}/garments` | List garments of a garment type | ProgramAdmin, AccountManager |
| POST | `/garments/{id}/apply-emblem` | Apply or change an embroidered emblem | ProgramAdmin, AccountManager |
| POST | `/garments/{id}/start-wash` | Reserve a slot and move a garment into wash | CleanroomTech |
| POST | `/garments/{id}/finish-wash` | Finish wash; garment returns to plant | CleanroomTech |
| POST | `/garments/{id}/retire` | Retire a garment for damage | ProgramAdmin |
| POST | `/assignments` | Assign a garment to a wearer | AccountManager |
| GET | `/assignments/{id}` | Fetch an assignment | ProgramAdmin, AccountManager |
| GET | `/assignments` | List assignments (filter by garment, wearer, account, status) | ProgramAdmin, AccountManager |
| POST | `/assignments/{id}/return` | Return a garment | AccountManager |
| POST | `/assignments/{id}/declare-loss` | Declare a garment lost | AccountManager |
| POST | `/assignments/{id}/declare-damage` | Declare a garment damaged | AccountManager |
| POST | `/routes` | Create a delivery route | ProgramAdmin |
| GET | `/routes/{id}` | Fetch a route | ProgramAdmin, RouteDriver |
| POST | `/routes/{id}/stops` | Add a stop to a route | ProgramAdmin |
| GET | `/routes/{id}/stops` | List stops on a route | ProgramAdmin, RouteDriver |
| GET | `/route-stops/{id}` | Fetch a route stop | ProgramAdmin, RouteDriver |
| GET | `/route-stops` | List route stops (filter by account) | ProgramAdmin, RouteDriver, AccountManager |
| POST | `/route-stops/{id}/service-visits` | Schedule a weekly service visit | ProgramAdmin, RouteDriver |
| GET | `/service-visits/{id}` | Fetch a service visit | ProgramAdmin, RouteDriver, AccountManager |
| GET | `/route-stops/{id}/service-visits` | List visits for a stop | ProgramAdmin, RouteDriver, AccountManager |
| GET | `/service-visits` | List service visits (filter by account) | ProgramAdmin, RouteDriver, AccountManager |
| POST | `/service-visits/{id}/pickup` | Pick up soiled garments and record the scan | RouteDriver |
| POST | `/service-visits/{id}/deliver` | Deliver clean garments; compute provisional charge | RouteDriver |
| POST | `/service-visits/{id}/reconcile` | Reconcile the visit; finalized charge supersedes provisional | ProgramAdmin |
| GET | `/service-visits/{id}/charges` | List charges for a visit | ProgramAdmin, AccountManager |
| GET | `/service-charges/{id}` | Fetch a single service charge | ProgramAdmin, AccountManager |
| GET | `/service-charges` | List service charges (filter by account) | ProgramAdmin, AccountManager |
| POST | `/service-charges/{id}/settle` | Mark a charge paid; recompute account ledger | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_FK_INTEGRITY` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ACCOUNT_ON_HOLD` | 409 Conflict |
| `ERR_WEARER_NOT_ACTIVE` | 409 Conflict |
| `ERR_WEARER_HAS_GARMENTS` | 409 Conflict |
| `ERR_STOP_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STOP_SEQUENCE_CONFLICT` | 409 Conflict |
| `ERR_WASH_STATION_FULL` | 409 Conflict |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_STALE_VISIT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SOIL_COUNT_NEGATIVE` | 400 Bad Request |
| `ERR_VISIT_GARMENTS_NOT_CLEAN` | 409 Conflict |
| `ERR_CHARGE_ALREADY_SETTLED` | 409 Conflict |
| `ERR_PAGINATION_INVALID` | 400 Bad Request |
| `ERR_EMBLEM_TEXT_INVALID` | 400 Bad Request |
