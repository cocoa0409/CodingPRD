# Land Surveying Services API — Product Requirements Document

## 1. Introduction

A professional land-surveying firm runs every parcel job as a long, branching pipeline: a client orders a survey of a known type, deed and parcel research must clear title, a field crew is scheduled with calibrated instruments, raw measurements are recorded and reduced, a plat drawing is produced and sealed by a licensed surveyor, revisions may loop the drawing back through drafting, and finally the deliverable is released and an invoice is settled. This API is the system of record for that entire lifecycle. It exists to enforce the firm's operational discipline programmatically — that title is genuinely clear before a crew rolls out, that the surveyor who seals a plat is not the technician who recorded its underlying data, that closure error is within tolerance, that equipment is calibrated and not double-booked, and that the money charged to the client reflects exactly the work that was actually performed.

The platform serves six distinct operational roles whose duties are deliberately segregated, and the central tension it manages is **temporal**: orders advance through stages over real working days, fees are estimated up front but only frozen at billing time, and concurrent edits to an order (a revision applied here, a sibling plat sealed there) must never let one actor silently overwrite a view of the order that another actor has since changed. The sections below define the global contract every endpoint honors, then the business workflows that govern how survey orders, research packets, field assignments, instrument reservations, datasets, plat drawings, revision requests, deliverables, and invoices move from intake to a closed invoice.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly six roles, spelled precisely as follows: `Coordinator`, `Researcher`, `FieldTech`, `Drafter`, `Surveyor`, and `BillingClerk`. When an authenticated user attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Each of the six roles is **entity-backed by the `CrewMember` aggregate**. When `X-User-Role` is `Coordinator`, `X-User-ID` is the `id` of the acting `CrewMember`; the same holds for `Researcher`, `FieldTech`, `Drafter`, `Surveyor`, and `BillingClerk` — in every case `X-User-ID` is the `id` of the `CrewMember` performing the action. Ownership and authorship checks on any resource that references a `CrewMember` compare the resource's foreign-key field (for example a packet's `assigned_researcher_id`, a dataset's `recorded_by_id`, a plat's `drafted_by_id` or `sealed_by_id`, or an invoice's `issued_by_id`) against the relevant crew identity. The roles correspond one-to-one with the `role_type` enumeration carried on each `CrewMember`: the `COORDINATOR`, `RESEARCHER`, `TECH`, `DRAFTER`, `PLS`, and `BILLING_CLERK` values back the `Coordinator`, `Researcher`, `FieldTech`, `Drafter`, `Surveyor`, and `BillingClerk` roles respectively. The firm enforces **segregation of duties**: research, fieldwork, drafting, sealing, and billing are owned by different people, and the surveyor who seals a plat must not be the technician who recorded its source data — a constraint detailed in §3.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this system — `CrewMember`, `Instrument`, `SurveyOrder`, `ResearchPacket`, `FieldAssignment`, `InstrumentReservation`, `DataSet`, `PlatDrawing`, `RevisionRequest`, `Deliverable`, and `Invoice` — carries a standard set of system-managed fields:

- **`id`** (string): a unique, server-minted identifier formatted as a UUID. It carries no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp indicating when the resource was last modified. It is refreshed on every mutation of the resource.
- **`version`** (integer): a server-managed integer that begins at 1 on creation and increments by one on every mutation of the resource. It is the basis for the optimistic concurrency control described in §2.8.

Identifiers in this system carry no type prefix; a resource is addressed solely by its bare UUID.

### 2.5. Hierarchical Consistency and Automatic State Propagation

The entities in this system are peers linked by foreign-key references rather than nested URL ownership trees, but their **states are tightly coupled**, and many transitions on a child resource automatically propagate to the parent `SurveyOrder`. When a field assignment first starts, when a dataset is accepted, when the first plat is created, when a plat is sealed, when a revision un-seals a plat, and when a deliverable is released, the order itself advances or reverts as a side effect — the client does not separately request the order transition. Every such automatic propagation independently mutates the affected order: it refreshes the order's `updated_at` and increments its `version`. The same holds for the cascades described in §3 (an order cancellation flowing down through assignments, reservations, and instruments): each entity touched in the cascade has its own `updated_at` refreshed and `version` incremented.

Because resource references are validated left-to-right, any request whose path or body names a resource that does not exist is rejected with `ERR_NOT_FOUND`, evaluated in the order the identifiers appear, so the first missing identifier is the one reported.

### 2.6. Monetary Precision and Rounding

All monetary values in this system are stored and returned as **integer cents**; there are no fractional-cent values in any persisted field or response body. Wherever a computation produces a non-integer cent amount — specifically the per-band per-acre field-fee products, the rush surcharge product, and the tax product — the result is rounded to the nearest whole cent using the **round-half-up** convention (a value ending in exactly one half cent rounds upward). Each such product is rounded individually at the point the rule below specifies; sums of already-integer amounts (for example the sum of applied re-seal fees) are exact and require no further rounding. The specific formulas, their inputs, and their constants are given in §3.

### 2.7. Asset, License, and Calibration Integrity

Several invariants protect the firm's physical and professional assets. Every `Instrument` carries an `asset_tag` that must be unique across all instruments, compared as a case-sensitive exact match; an attempt to register an instrument whose `asset_tag` already exists is rejected with `ERR_DUPLICATE_ASSET_TAG`. A licensed surveyor's credentials live on the `CrewMember` as `license_number`, `license_state`, and `license_expires_on`; these are populated only for crew whose `role_type` is `PLS` and default to null otherwise. An instrument's recalibration deadline lives in `calibration_due_on`. The conditions under which an expired license blocks sealing, and under which calibration blocks a reservation, are stated alongside the workflows they guard in §3.

### 2.8. Optimistic Concurrency Control

Two write operations target the `SurveyOrder` aggregate indirectly and are therefore protected by optimistic concurrency control to prevent one actor from acting on a stale view of the order. Both require a non-optional `expected_order_version` field in the request body, carrying the client's last observed `version` of the parent `SurveyOrder`.

The first is **sealing a plat**. A request to seal a plat drawing must carry `expected_order_version` matching the current `version` of the plat's parent `SurveyOrder`. Sealing advances that order from `DRAFTING` to `SEALED` and increments the order's `version`; if another writer has already advanced the order since the client last read it — for example a revision-apply that bumped `revision_count`, or a sibling plat seal that already advanced the order — the supplied `expected_order_version` no longer matches, and the seal is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412).

The second is **issuing an invoice**. A request to issue an invoice must carry `expected_order_version` matching the current `version` of the order being billed. Issuing freezes the order's `final_fee_cents` from the order's then-current fee components; if a revision applied after the client last read the order has since bumped the order's `version` (and its fee components), issuing against the stale version is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), so the clerk cannot freeze a total computed from a view of the order that has since changed.

No other endpoint accepts or requires a version field; OCC applies only to these two operations.

### 2.9. Validation Ordering

When a single request could fail several checks, validations are evaluated in a fixed priority order so that the reported error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, before anything else. Role authorization (`ERR_FORBIDDEN_ROLE`) is checked next. Existence of every path- and body-referenced resource (`ERR_NOT_FOUND`) is checked third, left-to-right. Request-body well-formedness — all required fields present with valid types and valid enum values (`ERR_INVALID_REQUEST`) — is checked fourth, on every write endpoint. The state-machine legality of the requested transition (`ERR_INVALID_STATE`) is checked fifth, before any of the domain-specific business rules. On the two OCC-protected endpoints, the `expected_order_version` match (`ERR_STALE_ORDER_VERSION`) is checked after state legality and before the remaining business rules. Only once all of these pass does the system evaluate the business-referential, safety, constraint, and temporal rules described throughout §3. Where the relative ordering of those domain rules matters for a specific endpoint, §3 states it explicitly.

## 3. Business Logic & Workflows

### 3.1. Crew, Instruments, and the Order Intake Pipeline

The firm's people are modeled as crew members. A `Coordinator` registers each crew member with a `full_name` and a `role_type`, which is one of `COORDINATOR`, `PLS`, `TECH`, `RESEARCHER`, `DRAFTER`, or `BILLING_CLERK`. For a member whose `role_type` is `PLS`, the registration also supplies the surveyor's `license_number`, two-letter `license_state`, and `license_expires_on`; for every other role these three fields are null. A crew member is created with `active` defaulting to true, marking them available for scheduling, and the system maintains a computed `open_assignment_count` that starts at 0 and tracks how many of that member's `FieldAssignment` rows are currently in either `SCHEDULED` or `IN_PROGRESS` status. A `Coordinator` may also request a computed scheduling-risk read for any crew member, described in §3.8.

Instruments are registered by a `Coordinator` with a unique `asset_tag`, an `instrument_type` that is one of `TOTAL_STATION`, `GPS_RTK`, `LEVEL`, `DRONE`, or `SCANNER`, and a `calibration_due_on` date. A new instrument's `status` begins as `AVAILABLE`; over its life it moves to `RESERVED` while held for fieldwork and back to `AVAILABLE` when released, and may independently be `MAINTENANCE`.

A survey order is the spine of the whole pipeline. A `Coordinator` creates one with the `client_name`, the `survey_type` (one of `BOUNDARY`, `TOPO`, `ALTA`, or `ELEVATION`), the `parcel_apn` identifying the subject parcel, a five-digit `county_fips` code used to route deed research, the parcel's `acreage` (which must be greater than zero), an optional `rush` flag defaulting to false, and a client-requested `requested_due_date`. On creation the order's `status` is `INTAKE`. The order then walks the pipeline `INTAKE → RESEARCH → FIELD_READY → IN_FIELD → DATA_READY → DRAFTING → SEALED → DELIVERED`, and from any pre-`SEALED` state it may instead be cancelled to `CANCELLED`. Both `DELIVERED` and `CANCELLED` are terminal. The order also carries the computed flags and totals that the rest of this section fills in: `research_clear` (false until title clears), `base_fee_cents` and `estimated_fee_cents` (set at creation), `final_fee_cents` (0 until billing), and `revision_count` (0 until revisions are applied).

At creation the system sets `base_fee_cents` from the survey type and computes `estimated_fee_cents`; both calculations are detailed in §3.7. Advancing an order out of `INTAKE` into `RESEARCH` is a `Coordinator` action and is permitted only when exactly one `ResearchPacket` already exists for the order; it changes no fee. The cancellation action is available to a `Coordinator` from `INTAKE`, `RESEARCH`, `FIELD_READY`, `IN_FIELD`, `DATA_READY`, and `DRAFTING` — that is, whenever the order's status is not among `SEALED` and `DELIVERED` — and its cascade is described in §3.4.

### 3.2. Deed and Parcel Research

Once an order is in `RESEARCH`, a research packet drives the title investigation. A packet is opened (by a `Coordinator` or a `Researcher`) against an order via `order_id` and is assigned to a researcher via `assigned_researcher_id`; it may record the recorded `deed_book` and `deed_page` references and an `encumbrance_count` of liens and easements found, which defaults to 0. At most one research packet may exist per order — a second attempt is rejected with `ERR_DUPLICATE_CHILD`. The `assigned_researcher_id` must resolve to a crew member whose `role_type` is `RESEARCHER`; if it does not, the packet creation is rejected with `ERR_ROLE_MISMATCH`. A new packet's `status` is `OPEN`.

A `Researcher` begins the investigation, moving the packet from `OPEN` to `IN_PROGRESS`. Beginning is permitted only when the assigned researcher is a crew member whose `role_type` is `RESEARCHER` and whose `active` is true — otherwise `ERR_ROLE_MISMATCH` — and only when the parent order's status is `RESEARCH`. From `IN_PROGRESS` the packet resolves one of two ways. If the investigation found no encumbrances — that is, `encumbrance_count` is exactly zero — the `Researcher` may clear it, moving the packet to `CLEARED` and, as a side effect, setting the parent order's `research_clear` flag to true. Clearing is permitted **only** at exactly zero encumbrances; attempting to clear while `encumbrance_count` is one or more is rejected with `ERR_TITLE_NOT_CLEAR`. Alternatively, when `encumbrance_count` is at least one, the `Researcher` places the packet on hold, moving it to `TITLE_HOLD`; this advances nothing and leaves `research_clear` false. A held packet can be reopened: from `TITLE_HOLD` the `Researcher` begins again, returning it to `IN_PROGRESS` (permitted whenever the parent order is still in `RESEARCH`) so the title issues can be re-investigated. The `CLEARED` state is terminal for the packet.

With title cleared, the `Coordinator` advances the order from `RESEARCH` to `FIELD_READY`. This transition is permitted only when the order's `research_clear` is true, which is the case only after the order's research packet reached `CLEARED`; it changes no fee.

### 3.3. Field Scheduling, Instrument Reservations, and Data Capture

A `Coordinator` schedules fieldwork by creating a field assignment against an order (`order_id`) for a crew member (`crew_member_id`) over a window bounded by `scheduled_start` (inclusive) and `scheduled_end` (exclusive). The assigned crew member's `role_type` must be either `TECH` or `PLS` and the member must be active; otherwise the assignment is rejected with `ERR_ROLE_MISMATCH`. The window's `scheduled_end` must be strictly after its `scheduled_start`; an end at or before the start is rejected with `ERR_INVALID_WINDOW`. Additionally, the crew member may not be double-booked: if that member already holds another assignment in `SCHEDULED` or `IN_PROGRESS` status whose half-open interval from its start (inclusive) to its end (exclusive) overlaps this one, the request is rejected with `ERR_CREW_DOUBLE_BOOKED`. Adjacency is allowed — an assignment whose start equals another's end does not overlap and is accepted. On successful creation the assignment's `status` is `SCHEDULED`, the system computes `window_minutes` as the whole number of minutes in the window (see §3.7), and the crew member's `open_assignment_count` is incremented by one.

To hold equipment for a window, a `Coordinator` creates an instrument reservation naming the `assignment_id` and the `instrument_id`. The reservation copies its window from the assignment: `reserved_start` is taken from the assignment's `scheduled_start` (inclusive) and `reserved_end` from its `scheduled_end` (exclusive). Two checks guard the reservation. First, the instrument must not already be otherwise committed: if any other `HELD` reservation exists whose window, after being expanded by a turnaround buffer on each side, overlaps this window, the request is rejected with `ERR_INSTRUMENT_UNAVAILABLE`; the buffer is a sixty-minute turnaround pad applied symmetrically before the start and after the end of each reservation interval when testing for overlap. Second, the instrument's `calibration_due_on` must fall after the assignment's `scheduled_end` — an instrument whose calibration deadline is at or before the field window's end is out of calibration for that window and the reservation is rejected with `ERR_INSTRUMENT_OUT_OF_CALIBRATION`. On success the reservation's `status` is `HELD` and the instrument's `status` flips from `AVAILABLE` to `RESERVED`.

Fieldwork begins when a `FieldTech` starts an assignment, moving it from `SCHEDULED` to `IN_PROGRESS`. Starting is permitted only when the parent order's status is either `FIELD_READY` or `IN_FIELD` and the crew member is active. As a propagation side effect, if the parent order was still `FIELD_READY` when the first assignment starts, the order advances from `FIELD_READY` to `IN_FIELD`. When the work is done the `FieldTech` completes the assignment, moving it from `IN_PROGRESS` to `COMPLETED`; completing requires the assignment to currently be `IN_PROGRESS`, and as side effects every `HELD` reservation for that assignment is set to `RELEASED`, each freed instrument flips from `RESERVED` back to `AVAILABLE`, and the crew member's `open_assignment_count` is decremented by one. An assignment may also be cancelled while `SCHEDULED` — by either a `Coordinator` or a `FieldTech`, or as part of the order-cancel cascade — moving it from `SCHEDULED` to `CANCELLED`; cancellation likewise releases every `HELD` reservation for the assignment, flips each freed instrument back to `AVAILABLE`, and decrements the crew member's `open_assignment_count` by one. Both `COMPLETED` and `CANCELLED` are terminal for an assignment. A reservation's lifecycle is simply `HELD → RELEASED`.

Field data is recorded by a `FieldTech` or a `Surveyor`, who creates a dataset naming the producing `order_id` and `assignment_id`, the `recorded_by_id` of the crew member who recorded it, the `point_count` of surveyed points captured (which must be zero or greater), and the traverse `closure_error_ppm` in parts-per-million (also zero or greater). A new dataset's `status` is `RAW`. A `Drafter` or `Surveyor` reduces it from `RAW` to `REDUCED`, and a `Surveyor` accepts it from `REDUCED` to `ACCEPTED`. Accepting a dataset is the event that advances its parent order from `IN_FIELD` to `DATA_READY`, provided at least one dataset for that order has reached `ACCEPTED`. An order may not enter drafting until at least one of its datasets is `ACCEPTED`. The `recorded_by_id` captured here is load-bearing for the segregation-of-duties rule at sealing time, described in §3.5.

### 3.4. Order Cancellation and the Release Cascade

Cancelling an order is a `Coordinator` action available from any state that is not `SEALED` or `DELIVERED` — concretely `INTAKE`, `RESEARCH`, `FIELD_READY`, `IN_FIELD`, `DATA_READY`, or `DRAFTING`. When an order is cancelled, the system runs a depth-three release cascade so that no equipment is left stranded: every `FieldAssignment` for that order that is still `SCHEDULED` is driven to `CANCELLED`; each such cancelled assignment in turn releases each of its `HELD` instrument reservations to `RELEASED`; and each freed instrument flips from `RESERVED` back to `AVAILABLE`. As each assignment in the cascade is cancelled, the owning crew member's `open_assignment_count` is decremented by one, consistent with the direct-cancel behavior in §3.3. Every entity touched along this chain — the order, each assignment, each reservation, each instrument — has its `updated_at` refreshed and its `version` incremented. The order's own `status` becomes `CANCELLED`, which is terminal.

### 3.5. Plat Drafting, Sealing, and the Revision Loop

Once an order reaches `DATA_READY`, a `Drafter` produces a plat drawing from an accepted dataset, naming the `order_id`, the source `dataset_id`, and the `drafted_by_id` of the drafter. Creating the first plat for an order advances the order from `DATA_READY` to `DRAFTING` as a side effect, provided at least one of the order's datasets is `ACCEPTED`. A new plat's `status` is `DRAFTED`, its `sealed_by_id` is null, and its `sealed_at` is null. The `Drafter` submits the plat for review, moving it from `DRAFTED` to `UNDER_REVIEW`; this is permitted only when the plat's source dataset is in `ACCEPTED` status.

Sealing is the most heavily guarded operation in the system, reserved to a `Surveyor`, and it moves a plat from `UNDER_REVIEW` to `SEALED`. Several conditions must hold, and on this endpoint the OCC check from §2.8 also applies. The sealing crew member must be a `PLS` who is active and whose license has not expired — that is, whose `license_expires_on` is strictly after the current moment; a sealer who is not an active PLS, or whose license has lapsed, is rejected with `ERR_SEAL_NOT_LICENSED`. The sealing surveyor must also satisfy **segregation of duties**: the sealer's `id` must differ from the source dataset's `recorded_by_id`, so that the person who recorded the field data cannot also seal the plat derived from it; a match is rejected with `ERR_SEGREGATION_VIOLATION`. The source dataset's traverse closure error must be within tolerance: `closure_error_ppm` must be at most one hundred parts-per-million — a closure error of exactly one hundred seals, one hundred one is too coarse and is rejected with `ERR_CLOSURE_OUT_OF_TOLERANCE`. The seal request carries `sealed_by_id` (the sealing surveyor) and `expected_order_version`. On success the plat's `sealed_by_id` and `sealed_at` timestamp are set, and the parent order advances from `DRAFTING` to `SEALED`, which increments the order's `version`. As described in §2.8, if `expected_order_version` does not match the order's current version the seal is rejected with `ERR_STALE_ORDER_VERSION`. The plat drawing has no terminal state — it can re-enter the revision loop indefinitely.

Revisions cycle a plat back through drafting. A `Coordinator` requests a revision against a plat by naming the `plat_id`, a `reason` (one of `CLIENT_CHANGE`, `FIELD_ERROR`, or `DEED_DISCREPANCY`), and optional free-text `notes`. On creation the revision's `status` is `REQUESTED` and its `reseal_fee_cents` surcharge is computed from the reason (see §3.7), but that surcharge is not yet applied to any order. From `REQUESTED` the revision resolves two ways, both `Coordinator` actions. Rejecting it moves it from `REQUESTED` to `REJECTED` and changes nothing on the order. Applying it moves it from `REQUESTED` to `APPLIED` and drives the targeted plat into the revision cycle, but the precise side effects depend on the plat's state at the moment of application, and the two branches must be treated as distinct:

- **Applying to a plat that was `SEALED`.** The plat moves from `SEALED` to `IN_REVISION`; its seal is cleared, setting `sealed_by_id` back to null and `sealed_at` back to null. The revision's `reseal_fee_cents` is added to the order's `estimated_fee_cents`, and the order's `revision_count` is incremented by one. Because the order's sealed plat has been un-sealed, the parent order reverts from `SEALED` back to `DRAFTING` so the plat can be re-drafted, re-reviewed, and re-sealed; reaching `SEALED` again requires sealing a plat anew. This order revert is itself the un-seal bubble-up that returns a sealed order to drafting.
- **Applying to a plat that was `UNDER_REVIEW`.** The plat moves from `UNDER_REVIEW` to `IN_REVISION`. The order's `revision_count` is still incremented by one, but **no** re-seal fee is added, because the plat was never sealed and there is no seal to redo.

From `IN_REVISION` a `Drafter` resumes the draft, moving the plat from `IN_REVISION` back to `DRAFTED` for re-work; this is permitted only when the plat is currently `IN_REVISION`. The plat then re-walks `DRAFTED → UNDER_REVIEW → SEALED` as before.

### 3.6. Deliverables, Invoicing, and Settlement

A deliverable packages a sealed plat for the client. A `Coordinator` assembles one naming the `order_id`, the `plat_id` of the sealed plat to include, and a `format` of `PDF`, `DWG`, or `PAPER`; assembling requires the referenced plat to be `SEALED`, and the new deliverable's `status` is `ASSEMBLED`. Releasing the deliverable — a `Coordinator` action — moves it from `ASSEMBLED` to `RELEASED` (terminal) and drives the parent order from `SEALED` to `DELIVERED`. That order delivery is gated on two cross-entity conditions: the released deliverable must reference a `SEALED` plat for the order, and the order must already have an `Invoice` whose `lifecycle_status` is `ISSUED`. With both satisfied, the order becomes `DELIVERED`, which is terminal.

Billing runs on a `BillingClerk`. The clerk first creates a draft invoice for an order, naming the `order_id` and the `issued_by_id` of the issuing clerk; a new invoice begins with `lifecycle_status` of `DRAFT`, `payment_status` of `UNPAID`, and `subtotal_cents`, `tax_cents`, `total_cents`, `amount_paid_cents`, and `balance_due_cents` all 0. The invoice tracks two parallel axes: a **lifecycle axis** `DRAFT → ISSUED → CLOSED`, and a **payment axis** `UNPAID → PARTIAL → PAID` that advances independently of the lifecycle.

Issuing the invoice moves its `lifecycle_status` from `DRAFT` to `ISSUED` and is permitted only when the parent order's status is `SEALED` or `DELIVERED` and the invoice is still `DRAFT`. Issuing also carries the OCC `expected_order_version` field (§2.8) and is the moment the actual fee is frozen: the system computes the invoice's `subtotal_cents`, `tax_cents`, and `total_cents` per §3.7 and writes the resulting `total_cents` back onto the order as its `final_fee_cents`. At most one issued invoice may exist per order — a second issue attempt for an order that already has an issued or closed invoice is rejected with `ERR_DUPLICATE_CHILD`.

Payments are applied by the `BillingClerk` against an issued invoice, each carrying an `amount_cents`. A payment's amount must be greater than zero and must not exceed the invoice's current `balance_due_cents`; a non-positive amount or one that would overpay is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`. Each accepted payment adds its amount to `amount_paid_cents` and recomputes `balance_due_cents` as `total_cents` minus `amount_paid_cents`. If a payment leaves a positive balance, the invoice stays `ISSUED` and, on the first such partial payment, the `payment_status` advances from `UNPAID` to `PARTIAL` (the payment axis moving independently of the lifecycle axis). If a payment brings `balance_due_cents` to exactly zero, the invoice's `lifecycle_status` moves from `ISSUED` to `CLOSED` and its `payment_status` becomes `PAID`. `CLOSED` is terminal on the lifecycle axis.

### 3.7. Fee Estimation, Final Billing, Re-Seal Surcharges, and Window Computation

Four monetary and temporal computations run through the pipeline; all monetary results follow the integer-cents, round-half-up convention of §2.6.

**Survey-type base fee and the order estimate.** At order creation the system sets `base_fee_cents` from the survey type using the firm's tariff: a `BOUNDARY` survey is 120000 cents, `TOPO` is 180000 cents, `ALTA` is 350000 cents, and `ELEVATION` is 90000 cents. It then computes a tiered per-acre field-fee component over the order's `acreage`, charging marginal rates across ascending acreage bands. The first five acres are billed at 8000 cents per acre; the next fifteen acres — that is, acreage above five and up to twenty — are billed at 5000 cents per acre; and every acre beyond twenty is billed at 3000 cents per acre. The field fee is the sum over the bands the parcel reaches: for each band, multiply the number of acres that fall in that band by that band's per-acre rate and round the product half-up to a whole cent, then add the rounded band products together. Next a rush surcharge is computed but only when the order's `rush` flag is true: take the base fee plus the field fee, multiply that sum by thirty percent, and round the single product half-up to a whole cent; when `rush` is false the rush surcharge is zero. The order's `estimated_fee_cents` is then the base fee plus the field fee plus the rush surcharge. This estimate uses only order-creation inputs — `survey_type`, `acreage`, and the `rush` flag — and deliberately ignores any revisions, which do not yet exist.

**Final invoice fee.** When the invoice is issued, the actual fee is recomputed and may diverge from the estimate. The base component is the order's stored `base_fee_cents`, and the field component is recomputed from the order's `acreage` using exactly the same ascending-band math (first five acres at 8000 cents per acre, next fifteen at 5000, the remainder at 3000, each band product rounded half-up). The rush surcharge is computed the same way as in the estimate — thirty percent of base-plus-field, rounded half-up, charged only when the order's `rush` flag is true, and zero otherwise. The difference from the estimate is that all re-seal surcharges accumulated from revisions are now folded in: the system sums the `reseal_fee_cents` of every `RevisionRequest` whose targeted plat belongs to this order and whose `status` is `APPLIED` (revisions still `REQUESTED` or `REJECTED` are excluded), and this sum of already-integer fees is exact. The invoice `subtotal_cents` is the base plus the field fee plus the rush surcharge plus that applied-reseal total. Tax is then computed as 8.25 percent of the subtotal, rounded half-up to a whole cent, and stored as `tax_cents`. The invoice `total_cents` is `subtotal_cents` plus `tax_cents`, and that total is written back to the order as `final_fee_cents`. Because applied re-seal surcharges and tax did not exist at estimate time, `final_fee_cents` diverges from `estimated_fee_cents` whenever any revision was applied or whenever tax is nonzero.

**Re-seal surcharge by reason.** When a revision request is created, its `reseal_fee_cents` is set from its `reason` by table lookup: a `CLIENT_CHANGE` is 40000 cents, a `DEED_DISCREPANCY` is 25000 cents, and a `FIELD_ERROR` is 0 cents. This value is stored on the revision at creation but is only added to the order's `estimated_fee_cents` later, and only when the revision is applied to a plat that was `SEALED` (per §3.5); a revision applied to an `UNDER_REVIEW` plat contributes nothing to the order's fee.

**Field-window minutes.** When a field assignment is created (and whenever its window changes), the system computes `window_minutes` as the whole number of minutes between `scheduled_start` and `scheduled_end`: take the difference in seconds between the two instants, divide by sixty, and take the floor to a whole minute, discarding any remaining seconds.

### 3.8. Crew Scheduling-Risk Score

Separately from all fee accounting, a `Coordinator` may request a computed **scheduling-risk score** for a crew member; this is a read-only computation that mutates nothing. It blends two factors into an integer score from 0 to 100. The first is a **load factor**: take the crew member's `open_assignment_count`, cap it at five (so any count of five or more contributes the maximum), and divide that capped count by five to yield a value between 0 and 1. The second is a **license factor**: it is 1 when the crew member is a `PLS` whose `license_expires_on` falls within thirty days of the current moment, and 0 otherwise. The two factors are then blended with a sixty-percent weight on the load factor and a forty-percent weight on the license factor; that weighted blend is multiplied by one hundred and rounded half-up to produce the final integer risk score in the range 0 to 100. This risk computation lives entirely in the crew-scheduling domain and is independent of the order and invoice fee calculations.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action and every payment — return a `200 OK` status code. Read operations return `200 OK`. The request body, the resources mutated as side effects, and the validations each endpoint enforces are described in the §3 narratives above; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/crew-members` | Register a crew member | Coordinator |
| GET | `/crew-members/{id}` | Get a crew member | Coordinator, Researcher, FieldTech, Drafter, Surveyor, BillingClerk |
| GET | `/crew-members` | List crew members (filterable by `role_type`, `active`) | Coordinator, Researcher, FieldTech, Drafter, Surveyor, BillingClerk |
| GET | `/crew-members/{id}/risk-score` | Computed scheduling-risk score for a crew member | Coordinator |
| POST | `/instruments` | Register an instrument | Coordinator |
| GET | `/instruments/{id}` | Get an instrument | Coordinator, FieldTech |
| GET | `/instruments` | List instruments (filterable by `instrument_type`, `status`) | Coordinator, FieldTech |
| POST | `/survey-orders` | Create a survey order | Coordinator |
| GET | `/survey-orders/{id}` | Get a survey order | Coordinator, Researcher, FieldTech, Drafter, Surveyor, BillingClerk |
| GET | `/survey-orders` | List survey orders (filterable by `status`, `survey_type`) | Coordinator, Researcher, FieldTech, Drafter, Surveyor, BillingClerk |
| POST | `/survey-orders/{id}/start-research` | Advance an order from INTAKE to RESEARCH | Coordinator |
| POST | `/survey-orders/{id}/clear-research` | Advance an order from RESEARCH to FIELD_READY | Coordinator |
| POST | `/survey-orders/{id}/cancel` | Cancel an order and cascade-release its scheduled fieldwork | Coordinator |
| POST | `/research-packets` | Open a research packet for an order | Coordinator, Researcher |
| GET | `/research-packets/{id}` | Get a research packet | Coordinator, Researcher |
| GET | `/research-packets` | List research packets (filterable by `order_id`, `assigned_researcher_id`, `status`) | Coordinator, Researcher |
| POST | `/research-packets/{id}/begin` | Begin or re-open a packet (OPEN or TITLE_HOLD to IN_PROGRESS) | Researcher |
| POST | `/research-packets/{id}/clear` | Clear title (IN_PROGRESS to CLEARED) | Researcher |
| POST | `/research-packets/{id}/hold` | Place a title hold (IN_PROGRESS to TITLE_HOLD) | Researcher |
| POST | `/field-assignments` | Schedule a crew member on a field window | Coordinator |
| GET | `/field-assignments/{id}` | Get a field assignment | Coordinator, FieldTech |
| GET | `/field-assignments` | List field assignments (filterable by `order_id`, `crew_member_id`, `status`) | Coordinator, FieldTech |
| POST | `/field-assignments/{id}/start` | Start fieldwork (SCHEDULED to IN_PROGRESS) | FieldTech |
| POST | `/field-assignments/{id}/complete` | Complete fieldwork (IN_PROGRESS to COMPLETED) | FieldTech |
| POST | `/field-assignments/{id}/cancel` | Cancel a scheduled assignment | Coordinator, FieldTech |
| POST | `/instrument-reservations` | Hold an instrument for an assignment window | Coordinator |
| GET | `/instrument-reservations/{id}` | Get a reservation | Coordinator, FieldTech |
| GET | `/instrument-reservations` | List reservations (filterable by `assignment_id`, `instrument_id`, `status`) | Coordinator, FieldTech |
| POST | `/data-sets` | Record field data from an assignment | FieldTech, Surveyor |
| GET | `/data-sets/{id}` | Get a dataset | Coordinator, FieldTech, Drafter, Surveyor |
| GET | `/data-sets` | List datasets (filterable by `order_id`, `assignment_id`, `recorded_by_id`, `status`) | Coordinator, FieldTech, Drafter, Surveyor |
| POST | `/data-sets/{id}/reduce` | Reduce a dataset (RAW to REDUCED) | Drafter, Surveyor |
| POST | `/data-sets/{id}/accept` | Accept a dataset (REDUCED to ACCEPTED) | Surveyor |
| POST | `/plat-drawings` | Create a plat drawing from an accepted dataset | Drafter |
| GET | `/plat-drawings/{id}` | Get a plat drawing | Coordinator, Drafter, Surveyor |
| GET | `/plat-drawings` | List plat drawings (filterable by `order_id`, `dataset_id`, `drafted_by_id`, `sealed_by_id`, `status`) | Coordinator, Drafter, Surveyor |
| POST | `/plat-drawings/{id}/submit-review` | Submit a plat for review (DRAFTED to UNDER_REVIEW) | Drafter |
| POST | `/plat-drawings/{id}/seal` | Seal a plat (UNDER_REVIEW to SEALED); OCC on the order | Surveyor |
| POST | `/plat-drawings/{id}/resume-draft` | Resume drafting after revision (IN_REVISION to DRAFTED) | Drafter |
| POST | `/revision-requests` | Request a revision against a plat | Coordinator |
| GET | `/revision-requests/{id}` | Get a revision request | Coordinator, Drafter, Surveyor |
| GET | `/revision-requests` | List revision requests (filterable by `plat_id`, `status`) | Coordinator, Drafter, Surveyor |
| POST | `/revision-requests/{id}/apply` | Apply a revision (REQUESTED to APPLIED) | Coordinator |
| POST | `/revision-requests/{id}/reject` | Reject a revision (REQUESTED to REJECTED) | Coordinator |
| POST | `/deliverables` | Assemble a deliverable for a sealed plat | Coordinator |
| GET | `/deliverables/{id}` | Get a deliverable | Coordinator, BillingClerk |
| GET | `/deliverables` | List deliverables (filterable by `order_id`, `plat_id`, `status`) | Coordinator, BillingClerk |
| POST | `/deliverables/{id}/release` | Release a deliverable (ASSEMBLED to RELEASED); delivers the order | Coordinator |
| POST | `/invoices` | Create a draft invoice for an order | BillingClerk |
| GET | `/invoices/{id}` | Get an invoice | Coordinator, BillingClerk |
| GET | `/invoices` | List invoices (filterable by `order_id`, `issued_by_id`, `lifecycle_status`, `payment_status`) | Coordinator, BillingClerk |
| POST | `/invoices/{id}/issue` | Issue an invoice (DRAFT to ISSUED); freezes the final fee; OCC on the order | BillingClerk |
| POST | `/invoices/{id}/payments` | Apply a payment to an issued invoice | BillingClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_ROLE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_VIOLATION` | 422 Unprocessable Entity |
| `ERR_SEAL_NOT_LICENSED` | 422 Unprocessable Entity |
| `ERR_CLOSURE_OUT_OF_TOLERANCE` | 422 Unprocessable Entity |
| `ERR_TITLE_NOT_CLEAR` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_CREW_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_INSTRUMENT_UNAVAILABLE` | 409 Conflict |
| `ERR_INSTRUMENT_OUT_OF_CALIBRATION` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ASSET_TAG` | 409 Conflict |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CHILD` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
