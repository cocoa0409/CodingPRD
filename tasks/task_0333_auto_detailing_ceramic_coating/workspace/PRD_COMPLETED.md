# Auto Detailing & Ceramic Coating API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Auto Detailing & Ceramic Coating platform, a back-office API that runs the day-to-day operation of a detailing shop offering three package tiers — a basic wash, a full detail, and a long-cure ceramic coating. The business sells the same packages at four vehicle sizes, layers optional add-on services on top, and performs the work either in a fixed shop bay or out at the customer's location with a mobile crew. Because a ceramic coating must cure for a full day before the vehicle can be handed back, and because a shop bay or a mobile crew can only do one job at a time, the platform's central challenge is reconciling money and time: it must quote a price the moment a booking is made, hold the resource for exactly the right window, and then re-price the job once the work is actually done.

Three forces pull on every appointment at once. First, **pricing** layers a vehicle-size multiplier and an optional membership discount onto a tier's base price, then offsets a portion with a prepaid wash credit. Second, **scheduling** keeps two jobs from colliding on the same bay or crew, honoring a travel buffer for mobile work and blocking a bay through the entire ceramic cure. Third, **guarantees and loyalty** track each customer's realized spend to award a loyalty tier and let an unhappy customer file a rework claim that, if approved within the guarantee window, spawns a free re-do. Membership adds a recurring billing cycle that grants and expires wash credits. The API is consumed by four operator roles — the vehicle owner, the detailer who does the work, the scheduler who configures resources and adjudicates claims, and the shop manager who holds refund and override authority — each with a carefully bounded set of permissions described below.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is absent, or if `X-User-Role` does not name one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles: `Customer`, `Detailer`, `Scheduler`, and `ShopManager`. When an authenticated role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The `Customer` role is **entity-backed**: when `X-User-Role` is `Customer`, the value of `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on any resource that references a `Customer` compare the resource's `customer_id` to `X-User-ID`. A `Customer` may operate only on appointments and memberships that carry its own `customer_id`; an appointment is owned through its `customer_id`, and a membership through its `customer_id`. When a `Customer` acts on an appointment or membership whose `customer_id` does not equal `X-User-ID`, the request is rejected with `ERR_NOT_RESOURCE_OWNER`. For a rework claim, ownership is established through the original appointment the claim references.

The other three roles are **opaque** operator identities. When `X-User-Role` is `Detailer`, `Scheduler`, or `ShopManager`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it against any entity's `id`, and these roles are not subject to the ownership check above. A `Detailer` performs the hands-on work — checking vehicles in, attaching photos, marking add-on lines, and advancing the job through to release. A `Scheduler` owns catalog and resource configuration, drives the membership billing transitions, marks no-shows, and adjudicates rework claims. A `ShopManager` is the hierarchical override: it may perform every `Scheduler` operation and additionally holds the exclusive authority to refund a paid appointment, plus the authority to cancel appointments and memberships on a customer's behalf.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` below 1 or above 100, an `offset` below 0, or a `limit` or `offset` whose supplied value does not parse as an integer, is rejected with `ERR_VALIDATION`.

Unless otherwise specified, every list endpoint returns its resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Object Identity

Most resources in this system — `Customer`, `Membership`, `ServiceBay`, `MobileUnit`, `Appointment`, `AppointmentAddOn`, `JobPhoto`, and `ReworkClaim` — carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits captured when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value on creation and increments by one on every mutation; it is the basis for the optimistic-concurrency checks described in §2.7.

The three flat catalog resources — `PackageCatalog`, `VehicleSizeRate`, and `AddOn` — are configuration records that are not versioned. Each of these carries only an `id` (a server-minted UUID) and a `created_at` timestamp; they have no `updated_at` field and no `version` field. They are treated as immutable reference data once created.

Whenever a derived or computed field on a resource changes as part of a workflow — for example, when an appointment's money or schedule fields are recomputed — that recomputation is itself a mutation of the owning resource: it refreshes the resource's `updated_at` and increments its `version`.

### 2.5. Nested Resource Retrieval and Referential Integrity

Several endpoints address a resource through a path that names a parent and then a sub-resource — for example, the add-on lines, photos, and the per-line status of an appointment are reached through the appointment's `id` in the path. For any such path the server validates the path identifiers strictly left to right, and the first identifier in the path that does not resolve to an existing resource causes the request to be rejected immediately with `ERR_NOT_FOUND`, before any later identifier is examined. This applies to every path that targets a resource by its `id`.

Foreign-key references supplied in a request body are validated separately. When a create endpoint accepts a foreign key — a `customer_id`, a `service_bay_id`, a `mobile_unit_id`, an `appointment_id`, or an `original_appointment_id` — and that key does not point at an existing resource, the request is rejected with `ERR_FK_NOT_FOUND`. Path-identifier resolution (`ERR_NOT_FOUND`) is distinct from body foreign-key resolution (`ERR_FK_NOT_FOUND`): the former guards URL segments, the latter guards body fields.

### 2.6. Monetary Amounts, Minutes, and Rounding

All money in this system is stored and exchanged as whole integer cents — there are no fractional cents and no floating-point currency values. Wherever a price is scaled by a multiplier or a percentage, the multiplication is performed and then rounded to the nearest whole cent using the **round half up** rule (a result of exactly one-half cent rounds up). This rounding is applied at each individual multiplication step of the pricing calculation; once values are whole cents, any further additions and subtractions are exact and introduce no additional rounding. Basis-point values are interpreted as parts per ten-thousand: a basis-point figure multiplies an amount and the product is divided by ten thousand before rounding.

All durations are expressed in whole minutes, and all datetime arithmetic is performed in UTC. Schedule instants are compared at minute resolution.

### 2.7. Optimistic Concurrency Control

Two write operations in this system require the client to prove it is acting on a current view of a parent resource by carrying that resource's last observed `version`. These are the only two endpoints that take a version field; no other endpoint accepts or requires one.

The first guards booking a shop appointment against a service bay. A request to book an appointment in `SHOP` mode must carry `expected_service_bay_version`, and that value must equal the chosen `ServiceBay`'s current `version`. If a prior write has advanced the bay's `version` since the client last read it — for instance by flipping the bay into maintenance or booking another slot on it — the booking was composed against a stale view of the bay and is rejected with `ERR_STALE_BAY_VERSION` (HTTP 412), before any overlap arithmetic is attempted.

The second guards approving a rework claim. A request to approve a rework claim must carry `expected_claim_version`, and that value must equal the target `ReworkClaim`'s current `version`. The approval cascade legitimately mutates the claim — it records the spawned appointment's id and bumps the claim's `version` — so a second approval still carrying the pre-approval version is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412), which prevents a duplicate free appointment from being spawned.

A third version field, `expected_membership_version`, is required when cancelling a membership and is described with the membership lifecycle in §3.5; a mismatch with the membership's current `version` causes that cancellation to be rejected.

### 2.8. The Two Parallel Dimensions of an Appointment

An appointment evolves along two independent axes that live on the same record. The `work_status` axis tracks the physical progress of the job; the `payment_status` axis tracks money. The two advance on their own triggers and are validated independently — an appointment can be fully paid while still in service, or be physically ready while still unpaid. A request to drive either axis along a transition that is not legal from the appointment's current state on that axis is rejected with `ERR_INVALID_STATE`. The same `ERR_INVALID_STATE` guards illegal transitions on memberships and on rework claims. Every state transition on any entity is a mutation and therefore increments that entity's `version` and refreshes its `updated_at`.

### 2.9. Validation Ordering

When several checks apply to a single operation, they are evaluated in a fixed priority order so that the rejection a client sees is deterministic. Authentication is checked first: presence and validity of the headers (`ERR_UNAUTHENTICATED`), then role permission for the operation (`ERR_FORBIDDEN_ROLE`), then, for a `Customer` acting on its own resource, the ownership match (`ERR_NOT_RESOURCE_OWNER`). Existence is checked next: path-referenced resources (`ERR_NOT_FOUND`), then body foreign keys (`ERR_FK_NOT_FOUND`). Only then is the request body checked for well-formedness — required fields present, enum values legal, numbers in range, and an email containing an at-sign (`ERR_INVALID_REQUEST`). Business rules specific to each operation run after these gates, in the order described alongside each workflow in §3.

In particular, when booking a shop appointment, the operation-specific checks run in this sequence: location/resource coherence (`ERR_RESOURCE_MODE_MISMATCH`), then the ceramic-bay capability check (`ERR_BAY_NO_CERAMIC`), then the bay version (`ERR_STALE_BAY_VERSION`) which is evaluated before any overlap arithmetic, then resource availability (`ERR_RESOURCE_UNAVAILABLE`), then the bay time-overlap check (`ERR_BAY_TIME_CONFLICT`). For a mobile booking the coherence check is followed by resource availability and then the travel-buffer overlap check (`ERR_MOBILE_BUFFER_CONFLICT`).

## 3. Business Logic & Workflows

### 3.1. Configuring the Catalog and Resources

Before any vehicle can be booked, a `Scheduler` (or a `ShopManager`, who may perform every scheduler operation) lays down the reference data that drives pricing and scheduling. The **package catalog** holds one row per tier, keyed by `tier`, which is one of `WASH`, `FULL`, or `CERAMIC` and must be unique across rows. Each package row carries a `base_price_cents` — the price for a sedan-sized vehicle before any size multiplier or discount, which must be a positive number of cents — together with the timing the tier requires: `prep_minutes` (a non-negative number of preparation minutes), `service_minutes` (a positive number of active service minutes), and `cure_minutes` (a non-negative number of post-service cure minutes, during which the vehicle may not be released). A wash and a full detail have no cure phase, so their `cure_minutes` is zero; a ceramic coating cures for a full day, so its `cure_minutes` is one thousand four hundred forty minutes. Each row also carries `guarantee_days`, the length in days of the rework-guarantee window for that tier: a wash carries no guarantee (zero days), a full detail carries a one-week guarantee (seven days), and a ceramic coating carries a ninety-day guarantee.

The **vehicle-size rate** table holds one row per `vehicle_size`, which is one of `SEDAN`, `SUV`, `TRUCK`, or `XL` and must be unique. Each row carries a `size_multiplier_bps`, the multiplier applied to a tier's base price expressed in basis points and never below ten thousand (ten thousand basis points leaves the sedan baseline unchanged). The reference multipliers are ten thousand for a sedan, thirteen thousand for an SUV, fifteen thousand for a truck, and seventeen thousand five hundred for an XL vehicle.

The **add-on catalog** holds one row per `addon_code`, which is one of `ENGINE_BAY`, `PET_HAIR`, or `HEADLIGHT` and must be unique. Each add-on carries a `price_cents` (a positive flat price that is never scaled by vehicle size and never reduced by a membership discount) and an `extra_minutes` value (a non-negative number of minutes the add-on adds to the active service time when it is part of a job).

Resources come in two kinds. A **service bay** is created with a unique, non-empty `bay_code` and an optional `supports_ceramic` flag (default false) indicating whether the bay is climate-controlled enough to cure a ceramic coating; a bay's `status` begins `AVAILABLE` and may later be flipped between `AVAILABLE` and `MAINTENANCE`. Flipping a bay's status increments the bay's `version` — which is why a stale booking can be caught by the bay-version check. A **mobile unit** is created with a unique, non-empty `unit_code` and an optional `travel_buffer_minutes` (a non-negative integer, default thirty) giving the minimum gap the crew needs between two jobs for travel and setup; its `status` likewise begins `AVAILABLE` and toggles to `MAINTENANCE`. Registering a customer captures the customer's `email` — which must be unique across customers, non-empty, and contain an at-sign — and a non-empty `full_name`; a newly registered customer starts in the `BRONZE` loyalty tier with both spend totals at zero. Each of the uniqueness constraints in this section — a duplicate package `tier`, `vehicle_size`, `addon_code`, `bay_code`, `unit_code`, or customer `email` — is rejected with `ERR_INVALID_REQUEST`, evaluated after the body's individual fields have been validated for well-formedness.

### 3.2. Booking an Appointment: Pricing and the Occupancy Window

A booking is the heart of the system. A `Customer` may book on its own behalf, and a `Scheduler` or `ShopManager` may book for a customer. The request names the `customer_id`, the `tier`, the `vehicle_size`, the `location_mode` (`SHOP` or `MOBILE`), and the `scheduled_start_utc` instant. Location coherence is strict: a `SHOP` booking must name a `service_bay_id` and leave `mobile_unit_id` null, while a `MOBILE` booking must name a `mobile_unit_id` and leave `service_bay_id` null; any other combination is rejected with `ERR_RESOURCE_MODE_MISMATCH`. A `CERAMIC` job booked in `SHOP` mode additionally requires that the chosen bay's `supports_ceramic` be true, otherwise the booking is rejected with `ERR_BAY_NO_CERAMIC`. The chosen resource must be usable — a bay or unit sitting in `MAINTENANCE` causes `ERR_RESOURCE_UNAVAILABLE`. For shop bookings, the request also carries `expected_service_bay_version` for the stale-bay check described in §2.7. The `customer_id` foreign key is resolved (`ERR_FK_NOT_FOUND`) ahead of the body well-formedness checks per §2.9, but the supplied resource foreign key — `service_bay_id` for a `SHOP` booking or `mobile_unit_id` for a `MOBILE` booking — is resolved for existence (`ERR_FK_NOT_FOUND`) only after the `tier`, `vehicle_size`, `location_mode`, and `scheduled_start_utc` fields have been validated for well-formedness, so an ill-formed body field surfaces `ERR_INVALID_REQUEST` before a non-existent resource foreign key surfaces `ERR_FK_NOT_FOUND`.

At booking the system computes the **provisional price**. The calculation order is pinned because the credit depends on the discounted package, which depends on the membership flag. First the raw package price is the tier's `base_price_cents` multiplied by the chosen size's `size_multiplier_bps`, divided by ten thousand, rounded half up to whole cents. Then, if the customer counts as a member for this booking, a member discount is computed as that raw package price multiplied by the member discount rate of one thousand five hundred basis points, divided by ten thousand, rounded half up; if the customer is not a member the discount is zero. The discounted package price (the net package) is the raw package price minus that discount. Whether the customer counts as a member is frozen at booking into `is_member_at_booking`, a snapshot of whether the customer had an `ACTIVE` membership at the moment of booking; the provisional price uses this snapshot.

The add-on portion is the sum of the per-line snapshot prices of all add-on lines requested for the appointment; because each is already a whole-cent snapshot, the sum is exact. The `provisional_total_cents` reported at booking is the net package price plus the add-on total — it is reported **before** any credit is subtracted, because the credit is tracked separately in `credit_applied_cents` and flows into the outstanding balance rather than into the reported total. At booking, `final_total_cents` is seeded equal to `provisional_total_cents`; it stays equal until completion recomputes it.

The membership credit is handled at booking when `use_membership_credit` is set. The `use_membership_credit` flag is optional in the booking request and defaults to false when omitted (or supplied as null), so a booking that does not name it applies no credit. A credit may be applied only when the customer has an `ACTIVE` membership with `credits_remaining` greater than zero; if `use_membership_credit` is true but the membership is not `ACTIVE` or has no credits remaining, the booking is rejected with `ERR_NO_CREDIT_AVAILABLE`. When a credit is legitimately applied, `credit_applied_cents` is the smaller of the membership's frozen `wash_credit_value_cents` and the net package price — the credit offsets the package only, never the add-ons — and one credit is consumed (see the credit ledger in §3.5). When no credit applies, `credit_applied_cents` is zero.

The same booking computes the **occupancy window**. The added service minutes are the sum of the `extra_minutes_snapshot` of the requested add-on lines. The busy minutes are the tier's `prep_minutes` plus its `service_minutes` plus those added minutes. The cure minutes are the tier's `cure_minutes`. The `vehicle_release_utc` — the earliest instant the customer may take the vehicle — is the `scheduled_start_utc` advanced by the busy minutes plus the cure minutes, and this holds for both location modes. The `occupancy_end_utc` — the instant the resource is released for reuse — differs by mode: for a `SHOP` job the bay stays blocked through the cure, so `occupancy_end_utc` equals `scheduled_start_utc` plus busy minutes plus cure minutes (the same instant as release); for a `MOBILE` job the crew leaves before the cure, so `occupancy_end_utc` equals `scheduled_start_utc` plus busy minutes only.

Booking also captures the freshly computed `provisional_total_cents`, `final_total_cents`, `occupancy_end_utc`, `vehicle_release_utc`, and `is_member_at_booking` onto the new appointment, and triggers a recomputation of the customer's forward-looking projected spend (§3.6). A new appointment begins with `work_status` of `BOOKED` and `payment_status` of `UNPAID`, with `amount_charged_cents` and `amount_refunded_cents` at zero. Its `spawned_from_rework_claim_id` is null unless the appointment was created by an approved rework claim.

### 3.3. Avoiding Collisions: Bay Overlap and the Mobile Travel Buffer

A booking may not place two jobs on the same resource at conflicting times, and the two resource kinds use different geometry. For a shop bay the occupancy interval is half-open, running from `scheduled_start_utc` up to but not including `occupancy_end_utc`. A candidate booking conflicts with an existing appointment on the same `service_bay_id` when the candidate's start is strictly before the existing appointment's `occupancy_end_utc` and the existing appointment's start is strictly before the candidate's `occupancy_end_utc`; because the comparison is strict, two intervals that merely touch at a boundary (the candidate starting exactly when the other ends) do not conflict. Only existing appointments on that bay whose `work_status` is not one of `CANCELLED`, `NO_SHOW`, or `RELEASED` are considered. A conflict is rejected with `ERR_BAY_TIME_CONFLICT`.

For a mobile unit the geometry adds a travel buffer. Two jobs on the same `mobile_unit_id` need a gap of at least that unit's `travel_buffer_minutes` between them. Equivalently, a candidate conflicts with an existing job when the candidate's start is before the existing job's `occupancy_end_utc` plus the buffer, and the existing job's start is before the candidate's `occupancy_end_utc` plus the buffer. A gap of exactly the buffer is allowed; only a gap strictly shorter than the buffer conflicts. As with bays, only existing appointments on that unit whose `work_status` is not `CANCELLED`, `NO_SHOW`, or `RELEASED` are considered, and a violation is rejected with `ERR_MOBILE_BUFFER_CONFLICT`.

### 3.4. Performing the Work: Photos, Add-On Lines, and the Work Lifecycle

Once a vehicle is booked, the job moves through a sequence of work states driven by the `Detailer`. Each transition increments the appointment's `version`. Two photo gates punctuate the flow. A photo is attached by a `Detailer` by supplying its `phase` (`BEFORE` or `AFTER`) and a non-empty `image_url`; the photo records the `appointment_id` it documents. A `BEFORE` photo must exist before prep begins, and an `AFTER` photo must exist before service is finished; either gate, when unmet, rejects the transition with `ERR_PHOTO_REQUIRED`.

Checking in advances the appointment from `BOOKED` to `CHECKED_IN`. Check-in is allowed only when the appointment is still `BOOKED`, when the server's clock is at or past sixty minutes before `scheduled_start_utc`, and when the assigned resource is still usable — the `ServiceBay` for a shop job, or the `MobileUnit` for a mobile job, must be `AVAILABLE`. Starting prep advances `CHECKED_IN` to `IN_PREP` and requires that a `BEFORE` photo already exists. Starting service advances `IN_PREP` to `IN_SERVICE`.

Finishing service is where the two non-ceramic and ceramic paths diverge, and both require that an `AFTER` photo already exists. For a non-ceramic tier (where `tier` is not `CERAMIC`), finishing service advances `IN_SERVICE` directly to `READY`, and this transition triggers the final-price cascade described in §3.7. For a ceramic tier (where `tier` is `CERAMIC`), finishing service instead advances `IN_SERVICE` to `CURING`, because the coating must cure before the vehicle can be released; no price cascade fires yet. From `CURING`, finishing the cure advances the appointment to `READY`, but only once the server's clock is at or past `vehicle_release_utc`; an attempt before the cure has elapsed is rejected with `ERR_CURE_NOT_ELAPSED`. The cure-completion transition fires the same final-price cascade as the non-ceramic finish.

During service the `Detailer` records which add-on services were actually performed. An add-on line is added to a `BOOKED` appointment by naming its `addon_code`; an attempt to add a line to an appointment whose `work_status` is anything other than `BOOKED` is rejected with `ERR_INVALID_STATE` (checked after the body's `addon_code` is validated for well-formedness, and before the per-appointment uniqueness check). The line records its parent `appointment_id`, freezes `price_cents_snapshot` from the catalog `price_cents` and `extra_minutes_snapshot` from the catalog `extra_minutes` at the moment of line creation (so later catalog edits do not move it), and starts with `line_status` of `REQUESTED`. A given `addon_code` may appear at most once per appointment; a second line with an `addon_code` already present on the appointment is rejected with `ERR_INVALID_REQUEST`. Adding a line recomputes the appointment's occupancy window and provisional total (and reseeds `final_total_cents` equal to the new provisional total), recomputes the outstanding balance, increments the appointment's `version`, and recomputes the customer's projected spend. Later, during service, the `Detailer` marks each line's `line_status` as either `PERFORMED` or `SKIPPED`; a `SKIPPED` line is excluded from the final price. Marking a line carries no appointment work-status precondition — it is accepted whatever the appointment's current `work_status`, and it does not itself recompute the appointment's totals or occupancy window (only the `line_status` changes); the recomputation to the final price happens later when the appointment reaches `READY`. Marking a line increments the appointment's `version` (and the line's own `version`).

Releasing the vehicle advances the appointment from `READY` to `RELEASED`. Release is permitted only when the appointment is `READY` and either it is fully paid — its `payment_status` is `PAID`, equivalently its `outstanding_balance_cents` is zero — or it is a rework-spawned appointment (its `spawned_from_rework_claim_id` is non-null). An attempt to release a non-rework appointment that still owes money is rejected with `ERR_BALANCE_OUTSTANDING`. Release triggers the loyalty cascade described in §3.6, and if the released appointment was spawned by a rework claim, the claim it came from is moved to `FULFILLED` (§3.8). A `Detailer` or a `ShopManager` may release.

Two early exits close a booking that never runs. A `Customer` may cancel its own appointment while it is still `BOOKED`, but only when the appointment was not itself spawned by a rework claim — a rework appointment cannot be self-cancelled by the customer (its `spawned_from_rework_claim_id` must be null for the customer cancel to be allowed); a `ShopManager` may also cancel. Cancelling moves the appointment to `CANCELLED`, releases the occupancy window so the slot is reusable, and — if a deposit was being held (`payment_status` is `DEPOSIT_HELD`) — cascades a full deposit refund: the held amount is added to `amount_refunded_cents`, `payment_status` moves to `REFUNDED`, `outstanding_balance_cents` is recomputed, and the customer's projected spend and loyalty tier are recomputed because the cancelled appointment leaves the projected set. Separately, a `Scheduler` or `ShopManager` may mark a still-`BOOKED` appointment as `NO_SHOW`, but only once the server's clock is at or past thirty minutes after `scheduled_start_utc`. A no-show releases the occupancy window so the slot is reusable; if a deposit was being held, that deposit is forfeited — no refund is issued, `amount_refunded_cents` is left unchanged, and `payment_status` remains `DEPOSIT_HELD`.

### 3.5. Memberships, the Recurring Cycle, and the Wash-Credit Ledger

A membership is a recurring subscription that grants one wash credit per billing cycle. A membership is created — by the `Customer`, a `Scheduler`, or a `ShopManager` — by naming the subscriber's `customer_id` and a `default_vehicle_size` (one of `SEDAN`, `SUV`, `TRUCK`, or `XL`), which is the size used to value the recurring wash credit and to seed default appointments. A new membership begins in `PENDING_PAYMENT` with a `monthly_fee_cents` fixed at four thousand nine hundred cents and a `cycle_anchor_day` of thirty. The system holds at most one non-terminal membership per customer.

Activating a membership moves it from `PENDING_PAYMENT` to `ACTIVE`. On activation the system sets `cycle_start_utc` to the current instant, freezes `wash_credit_value_cents` to the member-discounted `WASH` price valued at the subscriber's `default_vehicle_size` (so a granted credit is worth that many cents against a package subtotal), grants one wash credit, sets the customer's `membership_id` to point at this membership, and makes future bookings price the customer as a member. The same activate operation also cures a past-due membership, moving it from `PAST_DUE` back to `ACTIVE` and, in that case, advancing `cycle_start_utc` by the thirty-day cycle and granting one fresh credit. A `Customer`, `Scheduler`, or `ShopManager` may activate.

The wash-credit ledger is a conserved-count system. The membership tracks `credits_granted_total` (every credit ever granted across all cycles), `credits_consumed_total` (credits applied to appointments), and `credits_expired_total` (credits that lapsed unused at a cycle rollover or termination). The `credits_remaining` is always `credits_granted_total` minus `credits_consumed_total` minus `credits_expired_total`, and this remaining count must never go negative; the invariant that granted equals consumed plus expired plus remaining holds at all times. When a booking legitimately applies a credit, `credits_consumed_total` increases by one and `credits_remaining` is recomputed.

The billing cycle advances on its own axis. Renewing an `ACTIVE` membership is a cyclic transition that keeps the membership `ACTIVE` and is permitted only once the server's clock is at or past `cycle_start_utc` advanced by the thirty-day cycle; renewal expires any credit left unconsumed from the prior cycle (adding that remaining count to `credits_expired_total`), then grants one new credit (incrementing `credits_granted_total`), recomputes `credits_remaining`, and advances `cycle_start_utc` by the thirty-day cycle. A `Scheduler` or `ShopManager` drives renewal. When a renewal payment fails, a `Scheduler` or `ShopManager` marks the membership `PAST_DUE` — permitted from `ACTIVE` only once the clock is at or past `cycle_start_utc` plus the thirty-day cycle. From `PAST_DUE`, if the grace period is exhausted (the clock is again at or past `cycle_start_utc` plus the thirty-day cycle), a `Scheduler` or `ShopManager` lapses the membership to `LAPSED`: all remaining credits are expired (added to `credits_expired_total`, with `credits_remaining` recomputed to zero), and a lapse cascade clears the customer's `membership_id` to null so future bookings price as a non-member.

Cancelling an `ACTIVE` membership is restricted to the `Customer` or a `ShopManager` and is the one membership operation guarded by optimistic concurrency: the request must carry `expected_membership_version` matching the membership's current `version`, and a mismatch is rejected with `ERR_STALE_CLAIM_VERSION`. (Cancellation, like renewal and lapse beyond their first checks, is gated by `ERR_INVALID_STATE` when attempted from a state from which it is not legal.) This `ERR_INVALID_STATE` state gate is evaluated before the `expected_membership_version` match, so a cancel attempt on a non-`ACTIVE` membership is rejected with `ERR_INVALID_STATE` even when the carried version is also stale. Cancelling moves the membership to `CANCELLED`, expires all remaining credits to `credits_expired_total` with `credits_remaining` recomputed to zero, and clears the customer's `membership_id` to null. Both `CANCELLED` and `LAPSED` are terminal.

### 3.6. Loyalty Tiers: Realized and Projected Spend

Each customer carries two spend figures and a loyalty band derived from one of them. The `chronological_lifetime_spend_cents` is the sum of `final_total_cents` over the customer's appointments whose `payment_status` is `PAID` — that is, realized spend only. The `projected_lifetime_spend_cents` is a forward-looking, what-if figure: it is the chronological realized spend plus the `provisional_total_cents` of the customer's appointments that are still in flight — those whose `work_status` is one of `BOOKED`, `CHECKED_IN`, `IN_PREP`, `IN_SERVICE`, `CURING`, or `READY` and whose `payment_status` is not `PAID` (the not-`PAID` condition avoids double-counting an appointment already realized in the chronological sum). The projected figure can place a customer one band higher than their realized tier and exists to support membership upsell.

The persisted `loyalty_tier` is driven by the realized chronological spend only. A customer is `GOLD` when their `chronological_lifetime_spend_cents` is at least one hundred fifty thousand cents, `SILVER` when it is at least fifty thousand cents (but below the gold threshold), and `BRONZE` otherwise; the comparisons are at-or-above, so a customer sitting exactly on a threshold qualifies for the higher band. The projected figure is recomputed whenever an appointment is created, cancelled, or marked no-show, and on every work transition. The realized chronological spend and the loyalty tier are recomputed when an appointment reaches release, when a paid appointment is refunded, and on the deposit and pay transitions. When release recomputes the realized spend, the released appointment's `final_total_cents` counts toward the sum only if its `payment_status` is `PAID`; the loyalty tier is then recomputed from the new realized spend, and if it rises into a higher band the customer's `loyalty_tier` field is updated. A refund removes the refunded appointment from the realized sum and likewise recomputes the tier.

### 3.7. Money Movement: Deposits, Payment, Refunds, and the Final Price

The payment axis runs in parallel with the work axis. The conserved payment quantity is the `outstanding_balance_cents`, defined as `final_total_cents` minus `credit_applied_cents` minus `amount_charged_cents` plus `amount_refunded_cents`. The payment-conservation invariant holds at all times: the amount charged minus the amount refunded plus the outstanding balance always equals `final_total_cents` minus `credit_applied_cents`. Every payment transition, and the final-price cascade, recomputes this balance.

A `Customer` (or a `ShopManager` on the customer's behalf) may capture a deposit on an `UNPAID` appointment whose `work_status` is not `CANCELLED`, `NO_SHOW`, or `RELEASED`. The request carries `deposit_cents`, which must equal the provisional total multiplied by the deposit rate of two thousand basis points, divided by ten thousand, rounded half up; a mismatch is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. Capturing a deposit adds `deposit_cents` to `amount_charged_cents`, moves `payment_status` to `DEPOSIT_HELD`, and recomputes the outstanding balance.

Paying moves an appointment to `PAID` and may be reached either from `UNPAID` or from `DEPOSIT_HELD`. In either case the appointment must be `READY` on the work axis, and the request carries `amount_cents`, which must equal the current `outstanding_balance_cents` (the full price net of any credit when paying from unpaid, or the remainder after deposit and credit when paying from deposit held); a mismatch is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. Paying adds `amount_cents` to `amount_charged_cents`, moves `payment_status` to `PAID`, and recomputes the outstanding balance to zero. A `Customer` or `ShopManager` may pay.

Refunding is exclusive to a `ShopManager` and may be applied to a `PAID` appointment. A refund is a full compensating reversal: `amount_refunded_cents` is increased by the full `amount_charged_cents`, `payment_status` moves to `REFUNDED` (a terminal payment state), and the outstanding balance is recomputed so the conservation invariant holds afterward with zero net cash retained. A refund also recomputes the customer's realized chronological spend and loyalty tier, because the refunded appointment no longer counts as realized.

The **final-price cascade** fires when an appointment reaches `READY` — whether from `IN_SERVICE` for a non-ceramic job or from `CURING` for a ceramic one. Its first hop recomputes `final_total_cents` using the final pricing variant; its second hop recomputes `outstanding_balance_cents` from that new final total. The final pricing variant differs from the provisional one in two ways: it uses the customer's **current** membership state — the customer counts as a member only if their `membership_id` is set and that membership's `status` is `ACTIVE` right now — rather than the booking-time `is_member_at_booking` snapshot, and it sums only the add-on lines whose `line_status` is `PERFORMED` rather than all requested lines. If the membership has lapsed since booking, or an add-on was skipped, the final total comes out below the provisional total. As with the provisional total, the final total is the net (discounted) package price plus the performed-add-on total; the credit, if any, is carried in `credit_applied_cents` and subtracted into the outstanding balance rather than into the reported total.

### 3.8. The Rework Guarantee

When a customer is unhappy with a completed job, they may file a rework claim, and an approved claim spawns a free re-do. A claim is filed — by the `Customer` or a `ShopManager` — by naming the `original_appointment_id` of the released appointment and a non-empty `reason`. The original appointment must be one that has reached `RELEASED`. At filing, the system computes `filed_within_window`: the guarantee window ends at the original appointment's `vehicle_release_utc` advanced by the original tier's `guarantee_days`, and the claim counts as within window only if the claim's `created_at` is strictly before that window end. A claim filed exactly at the window end is out of window. A claim begins in `SUBMITTED` status with no `rework_appointment_id`.

Approving a claim is restricted to a `Scheduler` or `ShopManager` and is guarded by optimistic concurrency: the request carries `expected_claim_version` matching the claim's current `version`, and a stale value is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412). Approval is permitted only from `SUBMITTED`, only when `filed_within_window` is true (otherwise the approval is rejected with `ERR_GUARANTEE_EXPIRED`), and only when the original appointment is `RELEASED`. Approving moves the claim to `APPROVED` and runs the rework-spawn cascade: its first hop creates a new appointment cloning the original's `tier`, `vehicle_size`, `location_mode`, and resource, beginning in `work_status` `BOOKED`, with `spawned_from_rework_claim_id` set to this claim and both `provisional_total_cents` and `final_total_cents` at zero (the zero-cost guarantee); its second hop forces the spawned appointment's `payment_status` to `PAID` with `outstanding_balance_cents` at zero, so it is releasable without any payment. The claim's `rework_appointment_id` is set to the spawned appointment's id, and the claim's `version` increments. Rejecting a claim, also by a `Scheduler` or `ShopManager`, simply moves it from `SUBMITTED` to `REJECTED`. Both `REJECTED` and `FULFILLED` are terminal.

The claim closes itself when its re-do is done. When the spawned rework appointment reaches `RELEASED`, the system moves the claim from `APPROVED` to `FULFILLED` — this is the system-driven transition that the release of a rework-spawned appointment triggers, recognizable because that appointment's `spawned_from_rework_claim_id` points back at the claim.

### 3.9. Test-Driving the Clock

Because so many transitions are gated on the passage of time — check-in windows, no-show timeouts, cure completion, membership renewal and lapse, and the guarantee window — the platform exposes an administrative capability, available to a `Scheduler` or `ShopManager`, that sets the server's current UTC instant to a supplied `to_iso8601` value. Advancing this logical clock is how time-based preconditions and window checks are exercised; it changes no business resource itself, only the instant the server treats as "now."

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (such as a customer, a catalog row, a resource, a membership, an appointment, an add-on line, a photo, or a rework claim) return a `201 Created` status code. Operations that modify an existing resource — every state transition, every payment action, every configuration flip, and the clock control — return a `200 OK` status code. List and read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/detailing/customers` | Register a customer | Scheduler, ShopManager |
| GET | `/detailing/customers/{id}` | Read a customer with computed loyalty fields | Customer, Scheduler, ShopManager, Detailer |
| GET | `/detailing/customers` | List customers | Scheduler, ShopManager |
| GET | `/detailing/customers/{id}/appointments` | List a customer's appointments | Customer, Scheduler, ShopManager, Detailer |
| GET | `/detailing/customers/{id}/memberships` | List a customer's memberships | Customer, Scheduler, ShopManager |
| POST | `/detailing/packages` | Create a package tier catalog row | Scheduler, ShopManager |
| GET | `/detailing/packages` | List package tiers | Customer, Scheduler, ShopManager, Detailer |
| POST | `/detailing/vehicle-size-rates` | Create a vehicle-size multiplier row | Scheduler, ShopManager |
| GET | `/detailing/vehicle-size-rates` | List vehicle-size rates | Customer, Scheduler, ShopManager, Detailer |
| POST | `/detailing/addons` | Create an add-on catalog row | Scheduler, ShopManager |
| GET | `/detailing/addons` | List add-ons | Customer, Scheduler, ShopManager, Detailer |
| POST | `/detailing/service-bays` | Create a shop bay | Scheduler, ShopManager |
| GET | `/detailing/service-bays/{id}` | Read a service bay | Customer, Scheduler, ShopManager, Detailer |
| GET | `/detailing/service-bays` | List service bays | Customer, Scheduler, ShopManager, Detailer |
| POST | `/detailing/service-bays/{id}/set-status` | Flip a bay between AVAILABLE and MAINTENANCE | Scheduler, ShopManager |
| POST | `/detailing/mobile-units` | Create a mobile unit | Scheduler, ShopManager |
| GET | `/detailing/mobile-units/{id}` | Read a mobile unit | Customer, Scheduler, ShopManager, Detailer |
| GET | `/detailing/mobile-units` | List mobile units | Customer, Scheduler, ShopManager, Detailer |
| POST | `/detailing/memberships` | Create a membership (PENDING_PAYMENT) | Customer, Scheduler, ShopManager |
| GET | `/detailing/memberships/{id}` | Read a membership with its credit ledger | Customer, Scheduler, ShopManager |
| POST | `/detailing/memberships/{id}/activate` | Activate or cure a past-due membership | Customer, Scheduler, ShopManager |
| POST | `/detailing/memberships/{id}/renew` | Roll the billing cycle forward | Scheduler, ShopManager |
| POST | `/detailing/memberships/{id}/mark-past-due` | Move ACTIVE to PAST_DUE on renewal failure | Scheduler, ShopManager |
| POST | `/detailing/memberships/{id}/lapse` | Move PAST_DUE to LAPSED | Scheduler, ShopManager |
| POST | `/detailing/memberships/{id}/cancel` | Cancel an ACTIVE membership | Customer, ShopManager |
| POST | `/detailing/appointments` | Book an appointment | Customer, Scheduler, ShopManager |
| GET | `/detailing/appointments/{id}` | Read an appointment | Customer, Scheduler, ShopManager, Detailer |
| GET | `/detailing/appointments` | List appointments, filterable by resource and customer | Customer, Scheduler, ShopManager, Detailer |
| POST | `/detailing/appointments/{id}/addons` | Add an add-on line to a booked appointment | Customer, Scheduler, ShopManager |
| GET | `/detailing/appointments/{id}/addons` | List add-on lines | Customer, Scheduler, ShopManager, Detailer |
| POST | `/detailing/appointments/{id}/addons/{addon_code}/set-line-status` | Mark an add-on line PERFORMED or SKIPPED | Detailer |
| POST | `/detailing/appointments/{id}/photos` | Attach a BEFORE or AFTER job photo | Detailer |
| GET | `/detailing/appointments/{id}/photos` | List job photos | Customer, Scheduler, ShopManager, Detailer |
| POST | `/detailing/appointments/{id}/check-in` | Advance BOOKED to CHECKED_IN | Detailer |
| POST | `/detailing/appointments/{id}/start-prep` | Advance CHECKED_IN to IN_PREP | Detailer |
| POST | `/detailing/appointments/{id}/start-service` | Advance IN_PREP to IN_SERVICE | Detailer |
| POST | `/detailing/appointments/{id}/finish-service` | Advance IN_SERVICE to CURING or READY | Detailer |
| POST | `/detailing/appointments/{id}/finish-cure` | Advance CURING to READY | Detailer |
| POST | `/detailing/appointments/{id}/release` | Advance READY to RELEASED | Detailer, ShopManager |
| POST | `/detailing/appointments/{id}/cancel` | Cancel a BOOKED appointment | Customer, ShopManager |
| POST | `/detailing/appointments/{id}/mark-no-show` | Mark a BOOKED appointment NO_SHOW | Scheduler, ShopManager |
| POST | `/detailing/appointments/{id}/capture-deposit` | Capture a deposit (UNPAID to DEPOSIT_HELD) | Customer, ShopManager |
| POST | `/detailing/appointments/{id}/pay` | Pay the balance (to PAID) | Customer, ShopManager |
| POST | `/detailing/appointments/{id}/refund` | Refund a PAID appointment | ShopManager |
| POST | `/detailing/rework-claims` | File a rework claim against a released appointment | Customer, ShopManager |
| GET | `/detailing/rework-claims/{id}` | Read a rework claim | Customer, Scheduler, ShopManager |
| GET | `/detailing/rework-claims` | List rework claims | Customer, Scheduler, ShopManager |
| POST | `/detailing/rework-claims/{id}/approve` | Approve a claim and spawn a free appointment | Scheduler, ShopManager |
| POST | `/detailing/rework-claims/{id}/reject` | Reject a claim | Scheduler, ShopManager |
| POST | `/detailing/_clock/set_current_utc` | Set the server's current UTC instant (test-driving) | Scheduler, ShopManager |

The appointment list endpoint accepts the optional filters `customer_id`, `service_bay_id`, `mobile_unit_id`, and `spawned_from_rework_claim_id` in addition to `limit` and `offset`. The rework-claim list endpoint accepts the optional filters `original_appointment_id` and `rework_appointment_id` in addition to `limit` and `offset`. All other list endpoints accept only `limit` and `offset`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_RESOURCE_MODE_MISMATCH` | 422 |
| `ERR_BAY_NO_CERAMIC` | 422 |
| `ERR_STALE_BAY_VERSION` | 412 |
| `ERR_RESOURCE_UNAVAILABLE` | 409 |
| `ERR_BAY_TIME_CONFLICT` | 409 |
| `ERR_MOBILE_BUFFER_CONFLICT` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PHOTO_REQUIRED` | 409 |
| `ERR_CURE_NOT_ELAPSED` | 409 |
| `ERR_NO_CREDIT_AVAILABLE` | 409 |
| `ERR_STALE_CLAIM_VERSION` | 412 |
| `ERR_GUARANTEE_EXPIRED` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_BALANCE_OUTSTANDING` | 409 |
| `ERR_VALIDATION` | 422 |
