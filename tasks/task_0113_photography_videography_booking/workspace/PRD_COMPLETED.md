# Photography & Videography Booking API — Product Requirements Document

## 1. Introduction

This document specifies the Photography & Videography Booking API, a back-office platform that carries a studio engagement from first inquiry through delivery and final accounting. The system is built around a single hub — the booking — to which contracts, payments, shoot windows, image galleries, print and album add-ons, and licensing rights all attach. Its purpose is to let a studio price a session deterministically, hold a client to a signed contract and a paid deposit before anyone picks up a camera, coordinate the lead photographer (and any second shooter) against a conflict-free calendar, and run the proofing-and-delivery loop without losing the thread between the creative work and the money owed.

The domain is unusually sensitive to timing and to parallel state. A booking advances along two independent tracks at once — a workflow track that follows the creative engagement (drafted, confirmed, shot, delivered, closed) and a payment track that follows the ledger (unpaid, deposit paid, paid in full, refund pending) — and the two evolve on their own schedules. Cancellation fees depend on how many days remain before the shoot when the cancellation is requested, second-shooter fees depend on the exact length of the window being staffed, and add-on pricing forks between volume-discounted prints and flat-rate albums. Because several of these figures are recomputed as orders and assignments come and go, the API leans on optimistic concurrency to keep a late writer from clobbering a total it never saw. The sections below fix the response contract and the system-wide invariants first, then narrate the business workflows that an implementer must reconstruct in full.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. The system recognizes exactly four roles, spelled precisely as follows: `Anonymous`, `Client`, `Photographer`, and `StudioAdmin`. A request that omits either header, or supplies one that is malformed, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is well-formed but not permitted to invoke the targeted operation (per the authorization column of the endpoint table in §4) is rejected with `ERR_FORBIDDEN_ROLE`.

The roles differ in how `X-User-ID` binds to persisted data. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's owning foreign key to `X-User-ID`. Concretely, a `Client` owns a `Booking` through its `client_id`, and that ownership reaches every resource hanging off the booking. When `X-User-Role` is `Photographer`, `X-User-ID` is the `id` of the acting `Photographer`; ownership checks compare the relevant photographer foreign key to `X-User-ID`, where a `Photographer` is treated as the owner of a `ShootSchedule` or `Gallery` by virtue of being the lead photographer (`lead_photographer_id`) on the underlying booking. When an entity-backed actor targets a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

The remaining two roles are not entity-backed. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity; an `Anonymous` caller is permitted only to self-register a new `Client` or a new `Photographer`, and nothing else. When `X-User-Role` is `StudioAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`, and a `StudioAdmin` is exempt from the per-resource ownership comparison described above.

This ownership binding also narrows what an entity-backed reader sees on the list (collection) endpoints. A `Client` listing payments, contracts, shoot schedules, or galleries sees only those whose booking it owns through `client_id`, and a `Photographer` listing shoot schedules or galleries sees only those whose booking it leads through `lead_photographer_id`; payments and contracts are not reachable by a `Photographer` at all. The booking list and the second-shooter-assignment lists are not narrowed this way — any authorized reader sees every matching row, scoped only by the declared query filters — and a `StudioAdmin`, being exempt from ownership, always sees every matching row on every list.

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

Endpoints that return collections are paginated through two query parameters. The `limit` parameter bounds the number of items returned; when omitted it defaults to 10, and a supplied value is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip; when omitted it defaults to 0.

Unless an endpoint states otherwise, list results are ordered by `created_at` ascending — the oldest resource first. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the count of all matching resources before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource is addressed by an `id` that the server mints as a UUID; clients never supply it, and it carries no type prefix. Most resources also carry a `created_at` and an `updated_at` timestamp, each an ISO 8601 UTC value with three fractional digits, where `created_at` is fixed at creation and `updated_at` is refreshed on every mutation. These resources additionally carry a `version`, an integer that begins at its initial value on creation and increments by one on every mutation; it is the basis for the optimistic concurrency checks described in §2.6.

One resource is deliberately leaner. A `ProofSelection` is immutable once recorded, so it carries only an `id` and a `created_at` — it has neither an `updated_at` field nor a `version` field. All other entities in the system (`Client`, `Photographer`, `SessionPackage`, `Booking`, `Payment`, `Contract`, `ShootSchedule`, `SecondShooterAssignment`, `Gallery`, `AddOnOrder`, and `LicenseGrant`) carry the full complement of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Derived Fields, Cascades, and Hierarchical Consistency

A booking exposes several computed monetary fields — `total_fee_cents`, `deposit_due_cents`, `amount_paid_cents`, `balance_due_cents`, and `cancellation_fee_cents` — that the server keeps in step with the events that drive them rather than accepting them as input. Whenever any of these is recomputed, the booking is mutated: its `updated_at` is refreshed and its `version` increments by one. The same holds for any other entity the server transitions automatically. When one operation touches more than one entity, every affected entity is mutated in turn; the workflow narratives in §3 enumerate each cascade explicitly, and an implementer must apply all of them, not only the primary effect.

Some state changes are produced by the server itself rather than by a direct client call on the changed resource. Completing a shoot bubbles its booking forward, finalizing a gallery bubbles its booking forward, and cancelling a booking ripples down into its schedule and any second-shooter assignments. These server-driven transitions still mutate each affected resource's `updated_at` and `version` exactly as a direct call would.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency, because each contends with recomputation of a booking total or a schedule window that another writer may already have advanced. On these two operations the relevant version field is a required input, not an optional one; on every other endpoint no version field is accepted.

Ordering an add-on against a booking requires `expected_booking_version` in the request body, carrying the `version` of the `Booking` the client last observed. If the booking's current `version` has moved on since then — because some other writer already applied an add-on, a settlement, or another mutation that bumped it — the request is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412). The same guard applies when cancelling an add-on order, which likewise carries `expected_booking_version` and is rejected with `ERR_STALE_BOOKING_VERSION` on a mismatch. This prevents a writer from layering an order onto a total it has not actually seen.

Assigning a second shooter to a shoot window requires `expected_shoot_schedule_version` in the request body, carrying the `version` of the `ShootSchedule` the client last observed. If the schedule's current `version` has advanced — most commonly because the window was rescheduled, which bumps the schedule's version — the assignment is rejected with `ERR_STALE_SCHEDULE_VERSION` (HTTP 412), since the billable window would otherwise be derived from a window that no longer exists.

### 2.7. Validation Order and Error Precedence

When a single request could fail several checks, the system evaluates them in a fixed priority order and returns the first failure it encounters, so that a lower-priority condition never masks a higher-priority one. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`). Role authorization for the endpoint comes next (`ERR_FORBIDDEN_ROLE`). Existence of every resource named in the URL path is checked third, left to right (`ERR_NOT_FOUND`). For an entity-backed actor acting on an owned resource, the ownership comparison comes fourth (`ERR_NOT_RESOURCE_OWNER`). Body foreign keys are then checked against existing parents (`ERR_INVALID_REFERENCE`). The legality of the requested state transition against the target's current state comes sixth (`ERR_INVALID_STATE`). The optimistic-concurrency version check on the two guarded writes comes seventh (`ERR_STALE_BOOKING_VERSION` or `ERR_STALE_SCHEDULE_VERSION`). Domain-specific business rules — the model-release gate, the signed-contract gate, scheduling conflicts, reschedule and revision limits, image sufficiency, payment-amount agreement, the shoot-end timing gate, uniqueness, and package activity — follow thereafter, each described alongside the workflow it guards. Generic request-shape validation also sits in this tail: any create or update whose body omits a required field, carries an enum value outside its permitted set, or violates a numeric constraint — such as an `amount_cents` that is not strictly positive, an `end_utc` that is not strictly after its `start_utc`, a `quantity` below one, or a `deposit_pct` that is not greater than zero and at most one — is rejected with `ERR_INVALID_REQUEST`.

### 2.8. Nested Resource Retrieval

Several resources are reached through a parent in the URL — for example a booking's add-on orders, a booking's license grants, a shoot window's second-shooter assignments, or a gallery's proof selections. For any such path the system validates each identifier from left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that names no existing resource. A request for assignments under a non-existent shoot schedule fails on the schedule before the assignments are ever consulted, and a request for proof selections under a non-existent gallery fails on the gallery first. The same left-to-right precedence governs create operations that target a nested collection.

### 2.9. Monetary Amounts, Hours, and Rounding

All money in the system is held and exchanged as integer cents — `base_fee_cents`, `overage_hourly_rate_cents`, `total_fee_cents`, `deposit_due_cents`, `amount_paid_cents`, `balance_due_cents`, `cancellation_fee_cents`, `amount_cents`, `assignment_fee_cents`, `unit_price_cents`, `line_total_cents`, `fee_cents`, and a photographer's `hourly_rate_cents` are every one of them whole-cent integers. Wherever a calculation produces a fractional cent it is rounded half up to the nearest whole cent. Two quantities are rounded in the time domain rather than the money domain: shoot-hour overage and a second shooter's billable hours are each rounded up to a whole number of hours before they are priced, as the relevant calculations in §3 spell out. These hour-rounding and cent-rounding steps are independent and both apply.

## 3. Business Logic & Workflows

### 3.1. Participants and the Session Catalogue

The studio's participants register themselves before any booking exists. A new `Client` is created from an `email`, a `full_name`, and a `phone`; the email must be non-empty and unique across all clients, and the new client starts in `ACTIVE` status, the only alternative being `ARCHIVED`. A new `Photographer` is created from an `email`, a `full_name`, a list of `skills`, and an `hourly_rate_cents`; the email is again non-empty and unique across photographers, the `skills` list must be non-empty with every member drawn from `PHOTO`, `VIDEO`, `DRONE`, and `EDITING`, the hourly rate must be zero or greater, and the photographer starts `ACTIVE` (versus `INACTIVE`). A registration that reuses an existing client or photographer email is rejected with `ERR_DUPLICATE_RESOURCE`.

A `StudioAdmin` curates the catalogue of session packages. A `SessionPackage` is defined by a display `name`, a `session_type` (one of `PORTRAIT`, `WEDDING`, `EVENT`, `COMMERCIAL`, or `PRODUCT`), and a `tier` (one of `BASIC`, `STANDARD`, or `PREMIUM`). Its pricing inputs are a `base_fee_cents` that must be strictly greater than zero, a number of `included_shoot_hours` that must be strictly positive, an `overage_hourly_rate_cents` of zero or more charged for hours beyond what is included, and an `included_edited_images` count of zero or more that sets the delivery threshold for the gallery. The package also pins a `deposit_pct`, the fraction of the booking total taken as the retainer, which must be greater than zero and at most one. Two booleans round out the package: `requires_model_release`, defaulting to false, which dictates whether a signed model release is mandatory before the shoot, and `active`, defaulting to true, which governs whether the package may currently be booked. Packages can be fetched individually or listed; the list view filters on `session_type`, `tier`, and `active`.

### 3.2. Opening a Booking and Pricing the Engagement

A `Client` (or a `StudioAdmin` acting on their behalf) opens an engagement by creating a booking from a `client_id`, a `package_id`, a `lead_photographer_id`, and the `requested_shoot_hours` desired, which must be strictly positive. The booking is born in `DRAFT` `workflow_status` and `UNPAID` `payment_status`, with `total_fee_cents`, `deposit_due_cents`, `amount_paid_cents`, `balance_due_cents`, and `cancellation_fee_cents` all initialized to zero; `total_fee_cents` then begins reflecting add-on and second-shooter activity as soon as the first such order or assignment is recorded (per the recomputation triggers below), while `deposit_due_cents` stays zero until it is pinned at confirmation. The referenced package must be bookable: if its `active` flag is false the create is rejected with `ERR_PACKAGE_INACTIVE`. A booking can be fetched with all of its computed fields, or listed with filters on `client_id`, `lead_photographer_id`, `package_id`, `workflow_status`, and `payment_status`.

The booking total, `total_fee_cents`, is assembled rather than entered. Start from the booked package's `base_fee_cents`. Then compute the shoot-hour overage as the booking's `requested_shoot_hours` minus the package's `included_shoot_hours`, treating any negative result as zero; round that overage up to a whole number of hours and multiply by the package's `overage_hourly_rate_cents` to get the overage charge, which is added to the base. To this base-plus-overage figure add the sum of `line_total_cents` over every add-on order on the booking still in `ORDERED` status, and add the sum of `assignment_fee_cents` over every second-shooter assignment still in `ASSIGNED` status on the booking's active shoot schedule — the active schedule being the most recently created non-terminal (`SCHEDULED` or `RESCHEDULED`) schedule of the booking, or, if every schedule is terminal, the most recently created schedule. Add-on orders that are `CANCELLED` and assignments that are `RELEASED` contribute nothing. This total is computed when the booking is confirmed and is recomputed whenever an add-on order is created or cancelled and whenever a second-shooter assignment is created or released.

The deposit, `deposit_due_cents`, is pinned at confirmation and never recomputed afterward. Multiply the booking's `total_fee_cents` at confirm time by the package's `deposit_pct` and round that product half up to whole cents. The retainer carries a floor of 5000 cents: if the rounded percentage figure is below that floor, the deposit is raised up to 5000 cents — except that the deposit can never exceed the total itself, so when the entire booking total is below 5000 cents the deposit is simply the total. In other words the deposit is the percentage-based amount when that amount is at least 5000 cents; when the percentage amount falls below 5000 cents but the total is 5000 cents or more, the deposit clamps up to the 5000-cent floor; and when the total is itself below 5000 cents the deposit equals the total.

The outstanding balance, `balance_due_cents`, is the running gap between what is owed and what has been collected. Sum the `amount_cents` of every `SETTLED` payment of kind `DEPOSIT` or `BALANCE` to get the captured amount, sum the `amount_cents` of every `SETTLED` `REFUND` payment to get the refunded amount, and take captured minus refunded as `amount_paid_cents`. The balance is then `total_fee_cents` minus `amount_paid_cents`, never allowed below zero. Pending and failed payments are ignored entirely. This balance is recomputed at confirmation and again on every payment settlement.

### 3.3. The Contract and Model-Release Gate

Before a booking can leave `DRAFT`, it must rest on a signed contract. A `StudioAdmin` drafts a `Contract` for a booking from its `booking_id` and an optional `includes_model_release` flag (default false), and the contract begins in `DRAFT` status. At most one non-`VOID` contract may exist for a given booking; a second one is rejected with `ERR_DUPLICATE_RESOURCE`. The administrator then dispatches the contract to the client, moving it `DRAFT → SENT`. The owning client signs it, moving it `SENT → SIGNED` and stamping `signed_at` with the server's current time read from the logical clock of §3.8; signing is permitted only when the contract is `SENT` and only by the client who owns the contract's booking. A contract may also reach `VOID` from either `DRAFT` or `SENT`, but only as a side effect of cancelling the booking — never as a direct client action.

This contract is what gates confirmation, described next. The model-release rule rides on the same gate: if the booked package has `requires_model_release` set to true, then the booking's contract must have `includes_model_release` equal to true, or confirmation is refused.

### 3.4. Confirming, Scheduling, and the Pre-Shoot Window

Confirmation by the owning `Client` (or a `StudioAdmin`) advances the booking `DRAFT → CONFIRMED` and is the moment the financials crystallize. Several preconditions guard it. The booking must currently be in `DRAFT`; otherwise the transition is illegal and yields `ERR_INVALID_STATE`. The booking's contract must exist and be `SIGNED`, or confirmation is rejected with `ERR_CONTRACT_NOT_SIGNED`. If the package requires a model release, the contract's `includes_model_release` must be true, or confirmation is rejected with `ERR_MODEL_RELEASE_REQUIRED`. A shoot schedule must already exist for the booking in `SCHEDULED` status. When all hold, confirmation recomputes `total_fee_cents`, pins `deposit_due_cents`, recomputes `balance_due_cents`, and bumps the booking's `version`.

A shoot window is itself created ahead of confirmation. A `StudioAdmin` or `Photographer` schedules a window from the booking's `booking_id`, a `start_utc`, and an `end_utc`, where the window is the half-open interval that begins at `start_utc` and runs up to but not including `end_utc`, and `end_utc` must be strictly after `start_utc`. The schedule is born `SCHEDULED` with `reschedule_count` at zero and `reschedule_reason` unset. A new window is refused if it strictly overlaps any other non-terminal (`SCHEDULED` or `RESCHEDULED`) shoot schedule of the same lead photographer; back-to-back windows that merely touch — where one ends exactly when the next begins — are allowed, with no buffer between them. The conflict is reported as `ERR_LEAD_PHOTOGRAPHER_BUSY`. Schedules can be fetched and listed, the list filtering on `booking_id`.

Weather and other disruptions are handled by rescheduling, a `StudioAdmin` operation that moves the window and is modeled as a self-loop: a schedule that is `SCHEDULED` becomes `RESCHEDULED`, and a schedule already `RESCHEDULED` stays `RESCHEDULED`, in both cases through the same operation. The request supplies a `new_start_utc`, a `new_end_utc`, and a `reason`, where the reason is one of `WEATHER`, `CLIENT_REQUEST`, or `PHOTOGRAPHER_REQUEST` and is recorded in `reschedule_reason`. Each successful move sets the window to the new interval, increments `reschedule_count` by one, and bumps the schedule's `version`. Rescheduling is permitted only while the schedule is `SCHEDULED` or `RESCHEDULED` and the underlying booking is `CONFIRMED`; an illegal state yields `ERR_INVALID_STATE`. A window may be moved at most three times: if `reschedule_count` has already reached three, a further move is rejected with `ERR_RESCHEDULE_LIMIT`. There is also a calendar guard described in §3.5: the new window must not collide with the existing commitments of any second shooter already staffed on this schedule.

### 3.5. Staffing a Second Shooter

A `StudioAdmin` may staff an additional photographer onto a shoot window. A `SecondShooterAssignment` is created against a shoot window from a `photographer_id` and the `expected_shoot_schedule_version` required by the concurrency guard of §2.6; the new assignment begins in `ASSIGNED` status, the only other status being `RELEASED`. Its billable extent is derived from the window, not entered: take the window's duration as `end_utc` minus `start_utc`, convert to hours, and round up to a whole number of hours to obtain `billable_hours`. The assignment fee, `assignment_fee_cents`, is then `billable_hours` multiplied by the staffed photographer's `hourly_rate_cents`, pinned on the assignment at creation. Because an `ASSIGNED` assignment feeds the booking total, creating one recomputes the booking's `total_fee_cents` and `balance_due_cents`.

Staffing is conflict-aware. A second-shooter assignment is rejected if the same photographer is already `ASSIGNED` to an overlapping window elsewhere, where overlap is judged not on the bare half-open windows alone but with a sixty-minute travel buffer extended on each side — so two windows whose nearest edges sit less than sixty minutes apart are treated as conflicting even when they do not literally overlap. That collision is reported as `ERR_SHOOTER_DOUBLE_BOOKED`. The reschedule guard mentioned in §3.4 is the mirror image of this rule: when a window carrying second shooters is moved, the proposed new interval must not overlap any of those same photographers' other `ASSIGNED` assignments on a different schedule, this time judged on the plain half-open intervals with no travel buffer; a collision there is reported as `ERR_SCHEDULE_CONFLICT`. When the schedule being moved has no assignments at all, that check is satisfied vacuously.

An assignment can be released by a `StudioAdmin`, moving it `ASSIGNED → RELEASED`; releasing it drops its contribution and so recomputes the booking's `total_fee_cents` and `balance_due_cents`. Assignments can be listed under their shoot window, fetched individually, or listed across the studio with filters on `photographer_id`, `shoot_schedule_id`, and `status`.

### 3.6. Payments, Settlement, and the Money Track

Payments move the booking's independent payment track, which evolves separately from the workflow track — a booking may already be `SHOT` while still only `DEPOSIT_PAID`. A `StudioAdmin` records a `Payment` against a booking from its `booking_id`, a `kind` (one of `DEPOSIT`, `BALANCE`, or `REFUND`), and an `amount_cents` that must be strictly positive even for a refund. A new payment is born `PENDING`, the other settlement states being `SETTLED` and `FAILED`. Payments can be fetched and listed, the list filtering on `booking_id`, `kind`, and `status`.

Settling a payment is a `StudioAdmin` action that drives the payment track, and the amount must agree exactly with what is owed for that kind or the settlement is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. Settling a `DEPOSIT` requires the booking to be `UNPAID` and the payment to be `PENDING` with its `amount_cents` equal to the booking's `deposit_due_cents`; on success the payment becomes `SETTLED`, the booking's `amount_paid_cents` and `balance_due_cents` are recomputed, and the payment track advances `UNPAID → DEPOSIT_PAID`. Settling a `BALANCE` requires the booking to be `DEPOSIT_PAID` and the payment to be `PENDING` with its `amount_cents` equal to the booking's current `balance_due_cents`; on success the track advances `DEPOSIT_PAID → PAID_IN_FULL`, again recomputing the paid and balance figures. Settling a `REFUND` requires the booking to be `REFUND_PENDING` and the payment to be `PENDING` with its `amount_cents` equal to the booking's `amount_paid_cents` minus its `cancellation_fee_cents`; on success the refund subtracts from `amount_paid_cents`, the balance is recomputed, and the track returns `REFUND_PENDING → UNPAID`, leaving the studio having retained exactly the cancellation fee. Every settlement bumps the booking's `version`. Attempting any settlement from the wrong payment state is rejected with `ERR_INVALID_STATE`.

### 3.7. Shooting, Proofing, and Delivery

Once the appointed time arrives the shoot is completed by the assigned `Photographer`, an action on the shoot schedule that also bubbles the booking forward. Completion is permitted only when the schedule is `SCHEDULED` or `RESCHEDULED`, when the booking's `payment_status` is `DEPOSIT_PAID` or `PAID_IN_FULL`, and when the current time has reached or passed the window's `end_utc`; a completion attempted before the window ends is rejected with `ERR_SHOOT_NOT_ENDED`, and a completion from a wrong state with `ERR_INVALID_STATE`. On success the schedule moves to `COMPLETED`, the booking's `workflow_status` advances `CONFIRMED → SHOT`, and the relevant versions bump. The booking must be `CONFIRMED` for this advance to be legal.

Image delivery runs through a gallery and its proofing loop. A `Photographer` or `StudioAdmin` creates one `Gallery` per booking from its `booking_id` — a second gallery on the same booking is rejected with `ERR_DUPLICATE_RESOURCE` — and the gallery starts in `PENDING_UPLOAD` with `revision_round` at zero and `delivered_image_count` at zero (until the first upload records it). The lead photographer then uploads edited images, supplying a `delivered_image_count` of at least one, which records the count and moves the gallery `PENDING_UPLOAD → PROOFING`; uploading requires the booking to be `SHOT`. While the gallery is `PROOFING`, the owning client may record a `ProofSelection` against it — the selection is tied to that gallery through its `gallery_id` — supplying a `selected_image_count` of at least one; each selection captures the gallery's current `revision_round` into its own `round_index` and is immutable thereafter. Proof selections can be listed under their gallery.

The owning client may also ask for changes, moving the gallery `PROOFING → REVISION_REQUESTED`; this is permitted only while the gallery is `PROOFING`, only for the client who owns the gallery's booking, and only while `revision_round` is below the cap of two — a request beyond that cap is rejected with `ERR_REVISION_LIMIT`. The photographer answers a revision by uploading again, which moves the gallery `REVISION_REQUESTED → PROOFING`, sets the new `delivered_image_count`, and increments `revision_round` by one, closing one turn of the loop. Finalization by the photographer moves the gallery `PROOFING → FINALIZED` and bubbles the booking `SHOT → DELIVERED`; it is permitted only while the gallery is `PROOFING` and only when `delivered_image_count` is at least the package's `included_edited_images`, an insufficient count being rejected with `ERR_INSUFFICIENT_IMAGES`. Galleries can be fetched and listed, the list filtering on `booking_id`.

### 3.8. Add-Ons, Licensing, and Closing the Books

Prints and albums are ordered as add-ons against a booking. An `AddOnOrder` is created from a `line_kind` (either `PRINT` or `ALBUM`), a `quantity` of at least one, a `unit_price_cents` strictly above zero, and the `expected_booking_version` demanded by §2.6. Its `line_total_cents` is pinned at creation by a pricing path that forks on the kind. For a `PRINT` order the per-unit price earns a marginal volume discount across three quantity bands: the first ten units price at the full `unit_price_cents`, units eleven through fifty price at ninety percent of unit price, and every unit beyond fifty prices at eighty percent of unit price. Each band's subtotal is computed and rounded half up to whole cents on its own, and the three rounded subtotals are then summed — the rounding happens per band, before the bands are added together. For an `ALBUM` order there is no discount: the line is `quantity` multiplied by `unit_price_cents`, plus a flat binding surcharge of 3500 cents. A new order is born `ORDERED` (the alternative being `CANCELLED`), and because it joins the booking total, creating it recomputes the booking's `total_fee_cents` and `balance_due_cents` and bumps the booking's `version`. Cancelling an order — which also carries `expected_booking_version` — moves it `ORDERED → CANCELLED`, recomputes the booking's `total_fee_cents` and `balance_due_cents`, and bumps the version again. Add-on orders can be listed under their booking.

Usage rights are granted as licenses. A `StudioAdmin` issues a `LicenseGrant` against a booking from a `usage_scope` (one of `PERSONAL`, `COMMERCIAL`, `EDITORIAL`, or `EXCLUSIVE`), a `territory` (one of `LOCAL`, `NATIONAL`, or `WORLDWIDE`), and a `term_months` of zero or more, where zero means a perpetual license. The grant's `fee_cents` is pinned at creation from a base of 20000 cents scaled by three factors multiplied together. The scope factor is 1.0 for `PERSONAL`, 2.5 for `COMMERCIAL`, 1.8 for `EDITORIAL`, and 4.0 for `EXCLUSIVE`. The territory factor is 1.0 for `LOCAL`, 1.5 for `NATIONAL`, and 2.2 for `WORLDWIDE`. The term factor is 1.0 plus one tenth of the number of effective years, where the effective term in months is the supplied `term_months` except that a perpetual grant (`term_months` of zero) is treated as a sixty-month term, and the number of years is that effective month count divided by twelve. The base, the scope factor, the territory factor, and the term factor are all multiplied together first, and only the final product is rounded half up to whole cents — a single rounding at the very end. A new grant is `ACTIVE`; a `StudioAdmin` may later revoke it, moving it `ACTIVE → REVOKED`. License grants can be listed under their booking.

A booking is cancelled by the owning `Client` (or a `StudioAdmin`), and the consequences depend on where it stands. Cancelling a `DRAFT` booking moves it `DRAFT → CANCELLED`, sets `cancellation_fee_cents` to zero, and voids the booking's contract if one exists by moving that contract to `VOID`. Cancelling a `CONFIRMED` booking moves it `CONFIRMED → CANCELLED` and triggers a deeper cascade. First the cancellation fee is computed: count the whole days from the current time to the active schedule's `start_utc`, and apply a fee percentage of twenty-five percent when that lead time is fourteen days or more, fifty percent when it is at least seven but fewer than fourteen days, and one hundred percent when it is under seven days; multiply the booking's pinned `deposit_due_cents` by that percentage and round half up to whole cents to obtain `cancellation_fee_cents`. Because the lead time is measured against the live clock at the instant of cancellation, the same booking can yield different fees depending on when the cancellation fires. The cancellation then cascades: the booking's `SCHEDULED` or `RESCHEDULED` shoot schedule is moved to `CANCELLED`, and that schedule cancellation in turn releases each `ASSIGNED` second-shooter assignment on it (moving each to `RELEASED`), with each release removing that assignment's contribution. After the releases settle, the booking's `total_fee_cents` and `balance_due_cents` are recomputed. Finally, if the booking's `amount_paid_cents` exceeds its `cancellation_fee_cents`, the payment track moves to `REFUND_PENDING` so a compensating refund can be settled; otherwise the payment track is left as it was. Every cancellation bumps the booking's `version`.

The engagement closes after delivery. A `StudioAdmin` closes a booking, moving it `DELIVERED → CLOSED`, which is permitted only when the booking is `DELIVERED` and its `payment_status` is `PAID_IN_FULL`; an attempt from any other state is rejected with `ERR_INVALID_STATE`. `CLOSED` and `CANCELLED` are the two terminal resting points of the workflow track.

Finally, to make the time-dependent rules testable, a `StudioAdmin` can drive the server's logical clock by supplying a `to_iso8601` instant; the server adopts that value as its current UTC time and reports it back as `current_utc`. This clock is what shoot completion compares against the window's `end_utc` and what cancellation reads when measuring lead time to the shoot's `start_utc`.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code. Operations that modify an existing resource — including the state-transition operations that drive the workflows above — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/studio/clients` | Register a client | Anonymous, StudioAdmin |
| GET | `/studio/clients/{id}` | Fetch a client | Client, StudioAdmin |
| POST | `/studio/photographers` | Register a photographer | Anonymous, StudioAdmin |
| GET | `/studio/photographers/{id}` | Fetch a photographer | Photographer, StudioAdmin |
| POST | `/studio/session-packages` | Create a session package | StudioAdmin |
| GET | `/studio/session-packages/{id}` | Fetch a session package | Client, StudioAdmin |
| GET | `/studio/session-packages` | List session packages | Client, StudioAdmin |
| POST | `/studio/bookings` | Create a draft booking | Client, StudioAdmin |
| GET | `/studio/bookings/{id}` | Fetch a booking with computed fields | Client, Photographer, StudioAdmin |
| GET | `/studio/bookings` | List bookings | Client, Photographer, StudioAdmin |
| POST | `/studio/bookings/{id}/confirm` | Confirm a draft booking | Client, StudioAdmin |
| POST | `/studio/bookings/{id}/cancel` | Cancel a booking | Client, StudioAdmin |
| POST | `/studio/bookings/{id}/close` | Close a delivered, paid-in-full booking | StudioAdmin |
| POST | `/studio/payments` | Create a pending payment against a booking | StudioAdmin |
| GET | `/studio/payments/{id}` | Fetch a payment | Client, StudioAdmin |
| GET | `/studio/payments` | List payments | Client, StudioAdmin |
| POST | `/studio/payments/{id}/settle` | Settle a pending payment | StudioAdmin |
| POST | `/studio/contracts` | Create a draft contract for a booking | StudioAdmin |
| GET | `/studio/contracts/{id}` | Fetch a contract | Client, StudioAdmin |
| GET | `/studio/contracts` | List contracts | Client, StudioAdmin |
| POST | `/studio/contracts/{id}/send` | Send a draft contract to the client | StudioAdmin |
| POST | `/studio/contracts/{id}/sign` | Client signs a sent contract | Client |
| POST | `/studio/shoot-schedules` | Schedule a shoot window for a booking | StudioAdmin, Photographer |
| GET | `/studio/shoot-schedules/{id}` | Fetch a shoot schedule | Client, Photographer, StudioAdmin |
| GET | `/studio/shoot-schedules` | List shoot schedules | Client, Photographer, StudioAdmin |
| POST | `/studio/shoot-schedules/{id}/reschedule` | Move a shoot window | StudioAdmin |
| POST | `/studio/shoot-schedules/{id}/complete` | Mark the shoot complete | Photographer |
| POST | `/studio/shoot-schedules/{id}/second-shooter-assignments` | Assign a second shooter to a shoot window | StudioAdmin |
| GET | `/studio/shoot-schedules/{id}/second-shooter-assignments` | List second-shooter assignments on a shoot window | Client, Photographer, StudioAdmin |
| GET | `/studio/second-shooter-assignments/{id}` | Fetch a single second-shooter assignment | Photographer, StudioAdmin |
| GET | `/studio/second-shooter-assignments` | List second-shooter assignments | Photographer, StudioAdmin |
| POST | `/studio/second-shooter-assignments/{id}/release` | Release a second-shooter assignment | StudioAdmin |
| POST | `/studio/galleries` | Create a gallery for a booking | Photographer, StudioAdmin |
| GET | `/studio/galleries/{id}` | Fetch a gallery | Client, Photographer, StudioAdmin |
| GET | `/studio/galleries` | List galleries | Client, Photographer, StudioAdmin |
| POST | `/studio/galleries/{id}/upload` | Upload edited images for proofing | Photographer |
| POST | `/studio/galleries/{id}/request-revision` | Request a proofing revision | Client |
| POST | `/studio/galleries/{id}/finalize` | Finalize the gallery | Photographer |
| POST | `/studio/galleries/{id}/proof-selections` | Record a proofing selection | Client |
| GET | `/studio/galleries/{id}/proof-selections` | List proof selections for a gallery | Client, Photographer, StudioAdmin |
| POST | `/studio/bookings/{id}/add-on-orders` | Order a print/album add-on | Client, StudioAdmin |
| GET | `/studio/bookings/{id}/add-on-orders` | List add-on orders for a booking | Client, StudioAdmin |
| POST | `/studio/add-on-orders/{id}/cancel` | Cancel an add-on order | Client, StudioAdmin |
| POST | `/studio/bookings/{id}/license-grants` | Grant a usage/licensing right | StudioAdmin |
| GET | `/studio/bookings/{id}/license-grants` | List license grants for a booking | Client, StudioAdmin |
| POST | `/studio/license-grants/{id}/revoke` | Revoke a license grant | StudioAdmin |
| POST | `/studio/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | StudioAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REFERENCE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_BOOKING_VERSION` | 412 |
| `ERR_STALE_SCHEDULE_VERSION` | 412 |
| `ERR_MODEL_RELEASE_REQUIRED` | 422 |
| `ERR_CONTRACT_NOT_SIGNED` | 422 |
| `ERR_SCHEDULE_CONFLICT` | 409 |
| `ERR_SHOOTER_DOUBLE_BOOKED` | 409 |
| `ERR_LEAD_PHOTOGRAPHER_BUSY` | 409 |
| `ERR_RESCHEDULE_LIMIT` | 409 |
| `ERR_REVISION_LIMIT` | 409 |
| `ERR_INSUFFICIENT_IMAGES` | 422 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_SHOOT_NOT_ENDED` | 409 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_PACKAGE_INACTIVE` | 422 |
