# Sign Fabrication & Installation API — Product Requirements Document

## 1. Introduction

A custom sign business carries a job from a designer's first sketch all the way to a powered, permitted, installed structure on a customer's storefront — and then keeps living with that sign through warranties and reorders for years afterward. This API is the system of record for that entire journey. It coordinates the people who do the work (designers proofing artwork, surveyors measuring sites, permit clerks chasing approvals, shop managers releasing fabrication, install crews operating bucket trucks) and the artifacts they produce (art proofs, priced estimates, site surveys, permits, fabrication work orders, install jobs, change orders, warranty claims, and reorders).

The central tension the product must resolve is sequencing. A sign cannot be fabricated before its artwork is approved, its price accepted, its site cleared, and its permits granted; it cannot be installed before it is built and passes quality control; and it cannot be safely raised onto a forty-foot pylon without the right equipment class and an aerially certified crew. Every milestone gates the next, and money flows alongside: an accepted estimate becomes a contracted total, change orders amend that total mid-build, and a reorder can clone a finished job at today's prices or yesterday's. This document specifies the data model, the state machines, the pricing arithmetic, and the validation order that together keep a sign project honest from `DESIGN` through `CLOSED`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across every endpoint. The business workflows that consume these rules live in Section 3.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If `X-User-Role` is missing or names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED`. When the header is present and valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly five roles, spelled precisely as follows: `ShopManager`, `Designer`, `Customer`, `Surveyor`, and `PermitClerk`. The `ShopManager` owns the project lifecycle — creating projects, drafting and sending estimates, releasing and steering work orders, registering crews and equipment, scheduling installs, applying change orders, adjudicating warranty claims, confirming reorders, and driving the test clock. A `Designer` authors and submits art proofs. A `Customer` makes the buying decisions: approving or rejecting proofs, accepting or declining estimates, and approving or rejecting change orders. A `Surveyor` creates and decides site surveys. A `PermitClerk` runs the permit lifecycle. Filing a warranty claim and requesting a reorder are shared between `ShopManager` and `Customer`. Read access to projects and their children is open to all five roles except where a specific endpoint's authorized list narrows it.

For all five roles, the `identity` carried by `X-User-ID` is opaque: it is an operator identifier that is not tied to any persisted entity and is never compared against any resource's `id`. The server does not perform owner-matching on `X-User-ID`; authorization is determined entirely by `X-User-Role` against the operation's permitted role set.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the start of the result set and defaults to 0.

Unless an endpoint states otherwise, list responses are sorted by creation timestamp in ascending order — the oldest resource first.

Every list response carries the pagination bookkeeping in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every entity in the system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. All of this system's entities — projects, proofs, estimates, surveys, permits, work orders, install jobs, crews, equipment, change orders, warranty claims, and reorders — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) that is refreshed on every mutation, and an integer `version` that begins at its initial value on creation and increments by one on each mutation.

Updates to computed fields count as mutations. When the server recomputes a project's `contract_total_cents`, advances its `phase`, or sets its `approved_estimate_id`, it refreshes that project's `updated_at` and increments its `version` — even though no client edited the project directly. This versioning underpins the optimistic concurrency control described in §2.7.

### 2.5. Hierarchical Consistency and Automatic Reconciliation

Most child resources belong to a parent sign project, and many child state changes ripple upward into the project's `phase` automatically, without the client touching the project resource directly. When a project's first art proof is approved, the project advances out of `DESIGN`. When an estimate is accepted, the project advances out of `ESTIMATING`. When a work order reaches readiness, the project advances out of `FABRICATION`. When an install job is completed, the project advances out of `INSTALL`. Each such bubble-up is itself a mutation of the project: it refreshes the project's `updated_at` and increments its `version`. The precise from/to states for each of these transitions are given in Section 3.

The system also performs lazy reconciliation of time-sensitive states on read. Reading a project re-evaluates auto-expiries: a `SENT` estimate whose validity instant has passed becomes `EXPIRED`, and an `APPROVED` permit whose expiry instant has passed becomes `EXPIRED`. These transitions are observed at read time and at the moment a dependent action (such as accepting an estimate or releasing a work order) consults the resource.

### 2.6. Nested Resource Retrieval and Existence Ordering

Many paths address a child resource nested under its parent project — for example, a permit, an estimate, or an install job under a specific project. For any such request, the system validates the path identifiers left to right: the project is resolved first, then the nested child, and the child must genuinely belong to the named project. If the project id does not exist, or if the child id does not exist or belongs to a different project, the request is rejected with `ERR_NOT_FOUND`. This existence check precedes any body validation, state check, or business rule, so an action against a child of a non-existent project fails on the parent before the child is ever consulted.

### 2.7. Optimistic Concurrency Control on Ledger-Mutating Operations

Two operations re-price the project's contracted ledger and can therefore lose data if performed against a stale view of the project: accepting an estimate and applying an approved change order. Both require the client to declare the project version it last observed, through a non-optional `expected_sign_project_version` field in the request body.

When a `Customer` accepts a sent estimate, the request must carry `expected_sign_project_version` equal to the target project's current `version`. If another writer has advanced the project's `version` since the client last read it — for instance, another estimate was already accepted and the project has already left `ESTIMATING` — the accept is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot overwrite a contract it never saw. Likewise, when a `ShopManager` applies an approved change order, the request must carry `expected_sign_project_version` equal to the project's current `version`; if a prior change order has already applied and advanced the version, the apply is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than double-counting a delta onto the ledger. No other endpoint accepts or requires a version field.

### 2.8. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents — `total_cents`, `material_cost_cents`, `labor_cost_cents`, `subtotal_cents`, `surcharge_cents`, `delta_total_cents`, `contract_total_cents`, `snapshot_total_cents`, `fee_cents`, and `material_rate_cents_per_sqft` are all whole-cent integers. Wherever a calculation produces a fractional cent, the result is rounded half up to the nearest whole cent at the specific step named in the pricing rules of Section 3; rounding is applied per component in a pinned order, never deferred to a single rounding at the end. The billed area is computed in whole square feet, rounded up. Equipment reach and clearance comparisons are exact comparisons in feet. Warranty coverage is computed by whole-day arithmetic in UTC.

### 2.9. The Permit-Requirement and Illumination Principle

Whether a project needs permits at all is a computed property, `permit_required`, set when the project is created. A project requires permits when its `jurisdiction_code` is not `COUNTY_C`, or when the sign is illuminated — that is, `permit_required` is true unless the project is both in `COUNTY_C` and not illuminated. Illumination is significant in two further ways: an `illuminated` project mandates an `ELECTRICAL` permit in addition to any structural permit, and illumination drives a surcharge in the estimate price. The `illuminated` and `rush` flags both default to false when omitted at project creation.

### 2.10. Resource Booking and Scheduling Integrity

Crews and equipment are shared resources booked against install windows, and the system protects them from conflicting commitments. An install job reserves its assigned crew and equipment for its scheduled window the moment it is scheduled, and releases those reservations when the job fails or is cancelled. Equipment may not be double-booked: a chosen equipment unit's window may not overlap another active install job's window, where overlap is evaluated on the half-open interval from window start (inclusive) to window end (exclusive). Crews are protected by a stricter, same-day rule that additionally enforces a buffer between adjacent jobs. The specific booking checks, their ordering, and their error codes are detailed in Section 3's scheduling workflow.

## 3. Business Logic & Workflows

### 3.1. Originating a Sign Project and the Design Loop

A `ShopManager` originates the engagement by creating a sign project, supplying the `customer_name`, the `site_address`, the permitting `jurisdiction_code` (one of `CITY_A`, `CITY_B`, or `COUNTY_C`), the `sign_type` (one of `MONUMENT`, `PYLON`, `WALL`, or `BLADE`), the sign's `face_width_in` and `face_height_in` in inches, and the `placement_height_ft` — the height above grade in feet where the bottom of the sign face will sit. Two optional booleans, `illuminated` and `rush`, default to false. Dimensions must be sensible: `face_width_in` and `face_height_in` must each be greater than zero, and `placement_height_ft` must be at least zero; a non-positive dimension is rejected with `ERR_INVALID_REQUEST`, as is a missing required field or an out-of-range enum. A fresh project is created in `DESIGN` phase, with `permit_required` computed per §2.9, and `contract_total_cents` initialized to 0.

The design conversation runs through art proofs. A `Designer` creates an art proof revision by supplying the `artwork_uri` of the uploaded asset and the `color_count` — the number of distinct ink or vinyl colors, which must be at least one. The system stamps each proof with a `revision_no`: the very first proof of a project is revision 1, and each successive proof takes the prior maximum revision number plus one. Every proof references its project through `sign_project_id`. A new proof is born in `DRAFT`. When a new revision is created and the project already holds a proof sitting in `REJECTED`, that rejected proof is closed out to `SUPERSEDED` as the new `DRAFT` revision takes over the loop.

A `Designer` submits a `DRAFT` proof for review, moving it `DRAFT → SUBMITTED`; submission is only valid while the proof is in `DRAFT` and the project is still in `DESIGN`. The `Customer` then renders a verdict on a `SUBMITTED` proof by supplying a `decision`. A decision of approval drives the proof `SUBMITTED → APPROVED`, but only if no other proof of the project is already `APPROVED`; an attempt to approve a second proof when one is already approved is rejected with `ERR_PROOF_ALREADY_APPROVED`. A decision of rejection drives the proof `SUBMITTED → REJECTED` and stores the supplied `reject_reason`. `REJECTED` is not a dead end — it is the pivot of the revision loop: the designer creates a new revision, which supersedes the rejected one, and the conversation continues. Approving the first proof bubbles the project up from `DESIGN` to `ESTIMATING`.

### 3.2. Pricing: Estimates, Surcharges, and the Contracted Total

With an approved proof in hand, a `ShopManager` drafts an estimate against it. The estimate payload names the `art_proof_id` of the approved proof it is priced against, the `substrate` (one of `ALUMINUM`, `ACRYLIC`, or `STEEL`), and the `valid_until_iso` quote-expiry instant. The estimate references its project through `sign_project_id`. The referenced proof must be an `APPROVED` proof of this project; a reference to a proof that is not approved is rejected with `ERR_REFERENCE_NOT_ELIGIBLE`. A new estimate is created in `DRAFT`, and the system immediately computes its price.

Pricing proceeds in a fixed order. First, the billed area `area_sqft` is the sign-face area in square inches — `face_width_in` multiplied by `face_height_in` — divided by 144 and then rounded up to the next whole square foot. The per-square-foot material rate `material_rate_cents_per_sqft` is selected from the substrate: 1800 cents for `ALUMINUM`, 2600 cents for `ACRYLIC`, and 3400 cents for `STEEL`. The `material_cost_cents` is `area_sqft` multiplied by `material_rate_cents_per_sqft`. Labor is color-driven: each distinct color carries a setup charge of 4500 cents, so color labor is `color_count` times 4500 cents, and this color-labor amount is then scaled by a substrate labor multiplier — 1.00 for `ALUMINUM`, 1.25 for `ACRYLIC`, and 1.50 for `STEEL` — with the scaled result rounded half up to whole cents to produce `labor_cost_cents`. The `subtotal_cents` is the sum of `material_cost_cents` and `labor_cost_cents`.

Surcharges then stack on the subtotal in a pinned order: illumination first, then rush. If the project is illuminated, an illumination surcharge of fifteen percent of the subtotal is taken, rounded half up to whole cents; otherwise it is zero. The rush surcharge, if the project carries the rush flag, is twenty percent — but it is computed on the illumination-inflated base, meaning the subtotal plus the illumination surcharge, again rounded half up to whole cents; otherwise it is zero. The `surcharge_cents` is the sum of the illumination and rush surcharges, and the estimate's `total_cents` is `subtotal_cents` plus `surcharge_cents`. The authoritative `color_count` for pricing is the count carried on the approved art proof.

A `ShopManager` sends a `DRAFT` estimate to the customer, moving it `DRAFT → SENT`. A sent estimate carries a deadline: once the clock reaches or passes its `valid_until_iso`, the estimate is observed to be `EXPIRED` on the next read or accept attempt, transitioning `SENT → EXPIRED`. The `Customer` accepts a `SENT` estimate (supplying the `expected_sign_project_version` per §2.7). Acceptance is refused if the quote has already lapsed — an accept at or after `valid_until_iso` first expires the estimate and is rejected with `ERR_ESTIMATE_EXPIRED` — and is refused if some other estimate of the project is already `ACCEPTED`, with `ERR_ESTIMATE_ALREADY_ACCEPTED`. A successful accept drives the estimate `SENT → ACCEPTED`, and as side effects it sets the project's `approved_estimate_id` to this estimate, sets the project's `contract_total_cents` to this estimate's `total_cents`, supersedes every other `SENT` or `DRAFT` estimate of the project to `SUPERSEDED`, bubbles the project up from `ESTIMATING` to `PERMITTING`, and increments the project's `version` by one. A `Customer` may instead decline a `SENT` estimate, driving it `SENT → DECLINED`.

The contracted total is a running ledger. At accept time it equals the accepted estimate's `total_cents` with no deltas yet. Thereafter, `contract_total_cents` equals the accepted estimate's `total_cents` plus the sum of `delta_total_cents` across only those change orders in `APPLIED` status — proposed, approved, or rejected change orders contribute nothing — accumulated in the order the change orders were applied (by apply-transition time ascending, breaking ties by creation time ascending). Because each delta is already a whole-cent integer, the running sum requires no further rounding.

### 3.3. Clearing the Site: Surveys and Permits

Before a sign can be built, the site must be cleared and the paperwork granted, all while the project sits in `PERMITTING`.

A `Surveyor` creates a site survey carrying the `measured_clearance_ft` (the vertical clearance measured on site, at least zero), the `overhead_obstruction` boolean (true when power lines or a canopy overhead force an aerial-restricted equipment class), and the `ground_bearing_ok` boolean (true when the footing and soil can support a monument or pylon base). The survey references its project through `sign_project_id` and is created in `PENDING`. The surveyor then decides the survey by supplying a `result`. A pass drives the survey `PENDING → PASSED`, but only after two safety gates clear: the measured clearance must be at least the project's `placement_height_ft`, failing which the pass is rejected with `ERR_CLEARANCE_INSUFFICIENT`; and if the project's `sign_type` is `MONUMENT` or `PYLON`, ground bearing must be confirmed, failing which the pass is rejected with `ERR_GROUND_BEARING_FAILED`. A fail drives the survey `PENDING → FAILED` with no gates.

A `PermitClerk` creates a permit by naming its `permit_kind` (`STRUCTURAL` or `ELECTRICAL`) and optionally an `expires_iso` approval-expiry instant. The permit references its project through `sign_project_id` and is created in `DRAFT`; its `fee_cents` is computed at creation from a jurisdiction-and-kind table. A `STRUCTURAL` permit costs 25000 cents in `CITY_A`, 32000 cents in `CITY_B`, and 0 cents in `COUNTY_C`; an `ELECTRICAL` permit costs 18000 cents in `CITY_A`, 21000 cents in `CITY_B`, and 12000 cents in `COUNTY_C`. The clerk submits a `DRAFT` permit, moving it `DRAFT → SUBMITTED`, but only if the project actually requires permits; submitting a permit when `permit_required` is false is rejected with `ERR_PERMIT_NOT_REQUIRED`. The clerk then decides a `SUBMITTED` permit by supplying a `decision`, driving it `SUBMITTED → APPROVED` or `SUBMITTED → DENIED`. An `APPROVED` permit carries its own expiry: once the clock reaches or passes its `expires_iso`, the permit is observed to be `EXPIRED` on read or at work-order release, transitioning `APPROVED → EXPIRED`. An illuminated project must carry an `ELECTRICAL` permit as a mandatory kind in addition to any structural permit.

### 3.4. Releasing Fabrication and Steering it Through QC

A `ShopManager` releases fabrication when the gates are satisfied, which drives the project from `PERMITTING` to `FABRICATION` and creates a fabrication work order in `RELEASED`. Release is gated twice: a site survey in `PASSED` status must exist for the project, failing which the release is rejected with `ERR_SURVEY_NOT_PASSED`; and if the project requires permits, every required permit kind must be `APPROVED` and not `EXPIRED`, failing which the release is rejected with `ERR_PERMIT_NOT_APPROVED`. The work order references its project through `sign_project_id` and the accepted estimate through `estimate_id`, and snapshots that estimate's `total_cents` into `snapshot_total_cents`, frozen for the life of the work order.

The work order then moves through production. A `ShopManager` starts a `RELEASED` work order, moving it `RELEASED → IN_PRODUCTION`. Production output is placed on a quality hold, moving the work order `IN_PRODUCTION → QC_HOLD`. From the hold, the manager records a quality decision by supplying `qc_pass`. The quality fork has two symmetric branches: when `qc_pass` is true, the work order passes `QC_HOLD → READY_FOR_INSTALL` and the project bubbles up from `FABRICATION` to `INSTALL`; when `qc_pass` is false, the work order loops back `QC_HOLD → IN_PRODUCTION` for rework, with no project phase change. A work order may also be cancelled from any of `RELEASED`, `IN_PRODUCTION`, or `QC_HOLD`, moving it to `CANCELLED` and driving the project's `phase` from `FABRICATION` to `CANCELLED`.

### 3.5. Scheduling and Executing the Installation

Once a work order is ready for install, a `ShopManager` schedules an install job. The schedule payload names the `work_order_id` of the work order being installed, the assigned `crew_id`, an optional `equipment_id`, and the window bounds `window_start_iso` and `window_end_iso` in UTC. The job references its project through `sign_project_id`. The referenced work order must be in `READY_FOR_INSTALL`; otherwise the schedule is rejected with `ERR_REFERENCE_NOT_ELIGIBLE`. The window must be coherent: `window_end_iso` must be strictly later than `window_start_iso`, or the request is rejected with `ERR_INVALID_REQUEST`. A scheduled job is created in `SCHEDULED`.

At schedule time the system derives the `required_equipment_class` from the project's `placement_height_ft` and the latest passed site survey's `overhead_obstruction`. When there is no overhead obstruction, the class is purely a height tier: a placement height of at most 8 feet needs nothing (`NONE`), a placement height above 8 feet but at most 20 feet needs a `LADDER`, and the lower edge of each tier is inclusive so that exactly 20 feet with no obstruction still resolves to `LADDER`. When the survey reports an overhead obstruction, the class is forced to `BUCKET_TRUCK` regardless of height — even when the placement height would otherwise sit in the ladder range. Anything requiring more than ladder height, or any obstruction case, lands on `BUCKET_TRUCK`.

When the derived class is not `NONE`, `equipment_id` is required, and the chosen equipment must be the right class and tall enough: a `BUCKET_TRUCK` requirement demands an equipment unit whose `equipment_class` is `BUCKET_TRUCK` with a `max_reach_ft` at least the placement height. A missing or mismatched equipment selection is rejected with `ERR_EQUIPMENT_REQUIRED`. Scheduling reserves the crew and the equipment for the window. The chosen equipment may not collide with another active install job: if its window overlaps an existing booking on the half-open interval from start (inclusive) to end (exclusive), the schedule is rejected with `ERR_EQUIPMENT_DOUBLE_BOOKED`. The chosen crew is held to a same-day rule: if it already has an overlapping window on the same day, or one that sits too close without the required buffer between adjacent jobs, the schedule is rejected with `ERR_CREW_DOUBLE_BOOKED`.

A `ShopManager` dispatches a `SCHEDULED` job, moving it `SCHEDULED → DISPATCHED`, but only if the crew is available and certified for the work: a crew whose `active` flag is false is rejected with `ERR_CREW_UNAVAILABLE`, and a job whose `required_equipment_class` is `BUCKET_TRUCK` demands a crew whose `certified_aerial` flag is true, failing which dispatch is rejected with `ERR_CREW_NOT_CERTIFIED`. Completing a `DISPATCHED` job drives it `DISPATCHED → INSTALLED`, bubbles the project up from `INSTALL` to `WARRANTY`, and anchors the warranty coverage clock at the completion timestamp. A dispatched job that goes wrong can be failed, moving it `DISPATCHED → FAILED` and releasing the crew and equipment bookings for the window; failure is not terminal, so a fresh install job may be scheduled to retry. A job may also be cancelled from `SCHEDULED` or `DISPATCHED`, moving it to `CANCELLED` and likewise releasing the bookings.

Crews and equipment are registered independently of any project. A `ShopManager` registers a crew with its `name`, and optional `certified_aerial` (defaulting to false) and `active` (defaulting to true) flags; crew availability and certification can later be updated, an operation that increments the crew's `version` by one. A `ShopManager` registers an equipment unit with its `asset_tag`, its `equipment_class` (`LADDER` or `BUCKET_TRUCK`), its `max_reach_ft` working reach in feet (greater than zero), and an optional `in_service` flag (defaulting to true) that, when false, marks a unit down for maintenance and unbookable.

### 3.6. Amending Scope: Change Orders and the Ledger

After a price is contracted, scope can still move, but only within a window. A `ShopManager` proposes a change order carrying a `reason` and any subset of the proposed overrides — a `new_face_width_in`, a `new_face_height_in`, and a `new_substrate` (`ALUMINUM`, `ACRYLIC`, or `STEEL`) — where any omitted field leaves that dimension or substrate unchanged. The change order references its project through `sign_project_id` and is created in `PROPOSED`. At proposal, the system computes the signed `delta_total_cents` by re-pricing the entire sign under the proposed scope and subtracting the accepted estimate's total. Specifically, it runs the full estimate pricing using the effective width (the proposed `new_face_width_in` if given, else the project's current `face_width_in`), the effective height (the proposed `new_face_height_in` if given, else the project's current `face_height_in`), and the effective substrate (the proposed `new_substrate` if given, else the accepted estimate's `substrate`), while holding the `color_count` from the accepted estimate's proof and keeping the project's `illuminated` and `rush` flags. The resulting re-scoped total minus the accepted estimate's `total_cents` is the delta — which can be negative when downgrading, for example from `STEEL` to `ALUMINUM`. The final rounding occurs inside each pricing run, not on the difference of the two totals.

A `Customer` approves a `PROPOSED` change order, moving it `PROPOSED → APPROVED`, and a `ShopManager` then applies an `APPROVED` change order. Both approval and application are confined to the change window: the project's `phase` must be `PERMITTING` or `FABRICATION`, and an attempt outside that window is rejected with `ERR_CHANGE_WINDOW_CLOSED`. The apply (which carries `expected_sign_project_version` per §2.7) drives the change order `APPROVED → APPLIED` and produces several coordinated effects: the project's `face_width_in`, `face_height_in`, and `substrate`-bearing scope are updated to the proposed values; the project's `contract_total_cents` has this change order's `delta_total_cents` added to it as a compensating ledger sync; and if a fabrication work order exists in `IN_PRODUCTION` or `QC_HOLD`, that work order is cancelled and a new `RELEASED` work order is created in its place, with the project's `phase` reset back to `FABRICATION` if it had already advanced. Applying also increments the project's `version` by one. A `Customer` may instead reject a `PROPOSED` change order, moving it `PROPOSED → REJECTED`.

### 3.7. Warranties and Closing Out the Project

When an install completes, the project enters `WARRANTY` and the coverage clock starts ticking from the install completion timestamp. A claim can be filed by either a `Customer` or a `ShopManager`. The claim payload names the `install_job_id` of the installed job being claimed against, the `defect_kind` (`ELECTRICAL`, `STRUCTURAL`, or `COSMETIC`), and the `reported_iso` instant the defect was reported. The claim references its project through `sign_project_id` and is created in `OPEN`. The referenced install job must be in `INSTALLED`; a claim against a job that is not installed is rejected with `ERR_REFERENCE_NOT_ELIGIBLE`.

At creation the system computes `covered`. Each defect kind has a coverage window measured in whole days from the install date: `ELECTRICAL` is covered for 365 days, `STRUCTURAL` for 1825 days, and `COSMETIC` for 90 days. The claim is covered when `reported_iso` falls strictly before the install date plus the coverage-window days; the boundary is exclusive, so a report exactly at the install date plus the window length is not covered. A `ShopManager` adjudicates an `OPEN` claim by supplying a `decision`: an approval drives the claim `OPEN → APPROVED`, but only if the claim is covered — approving an uncovered claim is rejected with `ERR_OUT_OF_WARRANTY` — while a denial drives the claim `OPEN → DENIED`. An `APPROVED` claim is later resolved by a `ShopManager`, moving it `APPROVED → RESOLVED`.

A `ShopManager` closes a project from `WARRANTY`, driving its `phase` to `CLOSED`, but only when no warranty claim of the project still sits in `OPEN` or `APPROVED`; an attempt to close with such a claim outstanding is rejected with `ERR_OPEN_CLAIM`. A project may also be cancelled by a `ShopManager` while it is still in `DESIGN`, `ESTIMATING`, or `PERMITTING`, driving its `phase` to `CANCELLED`; cancellation also supersedes every non-terminal art proof (those in `DRAFT` or `SUBMITTED`) and every non-terminal estimate (those in `DRAFT` or `SENT`) to `SUPERSEDED`. From `FABRICATION` onward a project can no longer be cancelled, and the attempt is rejected with `ERR_INVALID_STATE`.

### 3.8. Reordering a Finished Sign

A completed sign can be reproduced. A `ShopManager` or a `Customer` requests a reorder of a source project, supplying the `quantity` of identical signs to reproduce (at least one) and an optional `reprice` flag that defaults to true. The reorder references its source through `sign_project_id` and is created in `REQUESTED`. A `ShopManager` confirms a `REQUESTED` reorder, but only when the source project is `CLOSED`; confirming against a source that is not closed is rejected with `ERR_SOURCE_NOT_CLOSED`. Confirmation drives the reorder `REQUESTED → CONFIRMED` and clones a brand-new sign project in `DESIGN`, copying the source's sign-type and dimension fields, and records the clone's id in the reorder's `reorder_project_id`. The `reprice` flag governs the money: when it is true, the cloned project re-prices at current material rates; when it is false, the cloned project carries the source's `contract_total_cents` forward unchanged. A `REQUESTED` reorder may instead be cancelled by a `ShopManager`, moving it `REQUESTED → CANCELLED`.

### 3.9. Validation Ordering and the Test Clock

When several checks could fire on a single request, they are evaluated in a fixed priority so the most fundamental failure surfaces first. Authentication is checked first: a missing or unknown `X-User-Role` yields `ERR_UNAUTHENTICATED`. Authorization is next: a recognized role that is not permitted for the operation yields `ERR_FORBIDDEN`. Then path existence is resolved left to right per §2.6, yielding `ERR_NOT_FOUND` for the first missing or mis-parented identifier. Then request-body validity is checked — required fields present and correctly typed, enums in range, dimensions positive, and the install window coherent — yielding `ERR_INVALID_REQUEST`. Then, for transition endpoints, the target resource must actually be in a state from which the transition is defined, yielding `ERR_INVALID_STATE` when it is not. Only after these structural checks do the business rules run: referential eligibility (`ERR_REFERENCE_NOT_ELIGIBLE`), the survey safety gates, the crew certification gate, the equipment and crew booking conflicts, the work-order release prerequisites, and finally the optimistic concurrency check on accept and apply (`ERR_STALE_VERSION`). The OCC version check is the last gate, applied after the operation's own state and business preconditions have otherwise cleared.

For deterministic testing of all time-dependent behavior — estimate and permit expiry, and warranty coverage windows — a `ShopManager` can drive the server's logical clock through an administrative capability that sets the current UTC instant to a supplied `to_iso8601` value, after which every subsequent time-dependent evaluation uses that instant as "now".

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify, transition, or read an existing resource return `200 OK`. List endpoints accept the `phase`, `approved_estimate_id`, `status`, `crew_id`, `work_order_id`, `equipment_id`, `install_job_id`, `art_proof_id`, `sign_project_id`, `estimate_id`, `limit`, and `offset` query parameters where applicable, as noted in the workflows above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/sign-projects` | Create a sign project | ShopManager |
| GET | `/sign-projects` | List sign projects (filter by phase or approved_estimate_id) | ShopManager, Designer, Customer, Surveyor, PermitClerk |
| GET | `/sign-projects/{id}` | Get a sign project (re-evaluates auto-expiries) | ShopManager, Designer, Customer, Surveyor, PermitClerk |
| POST | `/sign-projects/{id}/cancel` | Cancel a project | ShopManager |
| POST | `/sign-projects/{id}/close` | Close a project from WARRANTY | ShopManager |
| POST | `/sign-projects/{id}/art-proofs` | Create an art proof revision | Designer |
| GET | `/sign-projects/{id}/art-proofs` | List art proofs of a project | ShopManager, Designer, Customer |
| POST | `/sign-projects/{id}/art-proofs/{proof_id}/submit` | Submit a DRAFT proof | Designer |
| POST | `/sign-projects/{id}/art-proofs/{proof_id}/decision` | Approve or reject a SUBMITTED proof | Customer |
| POST | `/sign-projects/{id}/estimates` | Create an estimate against an approved proof | ShopManager |
| GET | `/sign-projects/{id}/estimates` | List estimates of a project | ShopManager, Customer |
| POST | `/sign-projects/{id}/estimates/{estimate_id}/send` | Send a DRAFT estimate | ShopManager |
| POST | `/sign-projects/{id}/estimates/{estimate_id}/accept` | Accept a SENT estimate (OCC on project) | Customer |
| POST | `/sign-projects/{id}/estimates/{estimate_id}/decline` | Decline a SENT estimate | Customer |
| POST | `/sign-projects/{id}/site-surveys` | Create a pending site survey | Surveyor |
| GET | `/sign-projects/{id}/site-surveys` | List site surveys of a project | ShopManager, Surveyor |
| POST | `/sign-projects/{id}/site-surveys/{survey_id}/decide` | Pass or fail a PENDING survey | Surveyor |
| POST | `/sign-projects/{id}/permits` | Create a permit | PermitClerk |
| GET | `/sign-projects/{id}/permits` | List permits of a project | ShopManager, PermitClerk |
| POST | `/sign-projects/{id}/permits/{permit_id}/submit` | Submit a DRAFT permit | PermitClerk |
| POST | `/sign-projects/{id}/permits/{permit_id}/decide` | Approve or deny a SUBMITTED permit | PermitClerk |
| POST | `/sign-projects/{id}/fabrication-work-orders` | Release a fabrication work order | ShopManager |
| GET | `/sign-projects/{id}/fabrication-work-orders` | List work orders of a project | ShopManager |
| POST | `/sign-projects/{id}/fabrication-work-orders/{wo_id}/start` | Start production | ShopManager |
| POST | `/sign-projects/{id}/fabrication-work-orders/{wo_id}/qc-hold` | Place on QC hold | ShopManager |
| POST | `/sign-projects/{id}/fabrication-work-orders/{wo_id}/qc-decide` | QC pass or fail | ShopManager |
| POST | `/sign-projects/{id}/fabrication-work-orders/{wo_id}/cancel` | Cancel a work order | ShopManager |
| POST | `/crews` | Register an install crew | ShopManager |
| GET | `/crews/{id}` | Get a crew | ShopManager |
| PATCH | `/crews/{id}` | Update crew availability/certification | ShopManager |
| POST | `/equipment` | Register an equipment unit | ShopManager |
| GET | `/equipment/{id}` | Get an equipment unit | ShopManager |
| POST | `/sign-projects/{id}/install-jobs` | Schedule an install job | ShopManager |
| GET | `/sign-projects/{id}/install-jobs` | List install jobs of a project | ShopManager |
| POST | `/sign-projects/{id}/install-jobs/{job_id}/dispatch` | Dispatch a SCHEDULED job | ShopManager |
| POST | `/sign-projects/{id}/install-jobs/{job_id}/complete` | Complete a DISPATCHED job | ShopManager |
| POST | `/sign-projects/{id}/install-jobs/{job_id}/fail` | Fail a DISPATCHED job | ShopManager |
| POST | `/sign-projects/{id}/install-jobs/{job_id}/cancel` | Cancel an install job | ShopManager |
| POST | `/sign-projects/{id}/change-orders` | Propose a change order | ShopManager |
| GET | `/sign-projects/{id}/change-orders` | List change orders of a project | ShopManager, Customer |
| POST | `/sign-projects/{id}/change-orders/{co_id}/approve` | Approve a PROPOSED change order | Customer |
| POST | `/sign-projects/{id}/change-orders/{co_id}/apply` | Apply an APPROVED change order (OCC on project) | ShopManager |
| POST | `/sign-projects/{id}/change-orders/{co_id}/reject` | Reject a PROPOSED change order | Customer |
| POST | `/sign-projects/{id}/warranty-claims` | File a warranty claim | Customer, ShopManager |
| GET | `/sign-projects/{id}/warranty-claims` | List warranty claims of a project | ShopManager, Customer |
| POST | `/sign-projects/{id}/warranty-claims/{claim_id}/decide` | Approve or deny an OPEN claim | ShopManager |
| POST | `/sign-projects/{id}/warranty-claims/{claim_id}/resolve` | Resolve an APPROVED claim | ShopManager |
| POST | `/sign-projects/{id}/reorders` | Request a reorder of a CLOSED project | ShopManager, Customer |
| GET | `/sign-projects/{id}/reorders` | List reorders of a project | ShopManager, Customer |
| POST | `/sign-projects/{id}/reorders/{reorder_id}/confirm` | Confirm a reorder | ShopManager |
| POST | `/sign-projects/{id}/reorders/{reorder_id}/cancel` | Cancel a REQUESTED reorder | ShopManager |
| GET | `/estimates/{id}` | Get an estimate by id | ShopManager, Customer |
| GET | `/estimates` | List estimates filtered by FK | ShopManager, Customer |
| GET | `/fabrication-work-orders/{id}` | Get a work order by id | ShopManager |
| GET | `/fabrication-work-orders` | List work orders filtered by FK | ShopManager |
| GET | `/install-jobs/{id}` | Get an install job by id | ShopManager |
| GET | `/install-jobs` | List install jobs filtered by FK | ShopManager |
| GET | `/warranty-claims/{id}` | Get a warranty claim by id | ShopManager, Customer |
| GET | `/warranty-claims` | List warranty claims filtered by FK | ShopManager, Customer |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROOF_ALREADY_APPROVED` | 409 Conflict |
| `ERR_REFERENCE_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_ESTIMATE_EXPIRED` | 409 Conflict |
| `ERR_ESTIMATE_ALREADY_ACCEPTED` | 409 Conflict |
| `ERR_CLEARANCE_INSUFFICIENT` | 409 Conflict |
| `ERR_GROUND_BEARING_FAILED` | 409 Conflict |
| `ERR_PERMIT_NOT_REQUIRED` | 409 Conflict |
| `ERR_SURVEY_NOT_PASSED` | 409 Conflict |
| `ERR_PERMIT_NOT_APPROVED` | 409 Conflict |
| `ERR_EQUIPMENT_REQUIRED` | 409 Conflict |
| `ERR_EQUIPMENT_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_CREW_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_CREW_UNAVAILABLE` | 409 Conflict |
| `ERR_CREW_NOT_CERTIFIED` | 409 Conflict |
| `ERR_CHANGE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_OUT_OF_WARRANTY` | 409 Conflict |
| `ERR_OPEN_CLAIM` | 409 Conflict |
| `ERR_SOURCE_NOT_CLOSED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
