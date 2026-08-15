# Interfacility Transfer & Bed Placement API — Product Requirements Document

## 1. Introduction

A hospital transfer center sits at the intersection of clinical urgency, federal regulation, and scarce bed capacity. When a patient must move between facilities, the center has to determine and document its EMTALA obligation, find a receiving physician willing to accept, hold an appropriate bed, clear the payer or invoke the emergency exception, assemble the clinical packet, and track the transport to arrival — all while every refusal, diversion, and delay leaves a compliance audit trail. This document specifies the product requirements for the Interfacility Transfer & Bed Placement API, the system of record for that end-to-end workflow.

The API models facilities and their beds, the physicians who send and receive patients, and the transfer case that threads them together. It supports a cyclic negotiation between sending and receiving physicians — a refused case may be re-shopped to another facility any number of times — a server-side bed selector with a deterministic ranking policy, dual-variant transport time estimates, payer-notification SLAs with an emergency-exception path, bed holds with acuity-scaled expiry, automatic occupancy-saturation diversions, and a quality review process with pinned scoring math. Time is governed by a logical clock so that SLAs, hold expiries, and diversion windows are fully deterministic.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system declares six roles: `TransferCoordinator`, `SendingPhysician`, `ReceivingPhysician`, `BedManager`, `QualityReviewer`, and `Any`. `Any` is a read marker rather than an operating capacity — every declared role may read, and all GET endpoints admit `Any`.

Identity semantics differ by role, and they drive every ownership check in the system. When `X-User-Role` is `TransferCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. The same is true of `Any`, which carries no identity at all. When `X-User-Role` is `SendingPhysician` or `ReceivingPhysician`, `X-User-ID` is the `id` of the acting `Physician`; ownership checks on a transfer case compare the case's `sending_physician_id` or `receiving_physician_id` respectively to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_CASE_PHYSICIAN`. When `X-User-Role` is `BedManager`, `X-User-ID` is the `id` of the managed `Facility`; operations scoped to a facility compare the target facility's `id` to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_FACILITY_MANAGER`. When `X-User-Role` is `QualityReviewer`, `X-User-ID` is again the `id` of a `Physician`, but segregation of duties applies: the reviewer must not be the case's sending or receiving physician, and once assigned, only that reviewer may close the review.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock

All time in the system — timestamps on state transitions, hold expiries, notification SLAs, diversion windows, and every computed duration — reads a single logical clock, never the wall clock. Before any call is made, the logical clock reads exactly 2026-08-01T00:00:00Z and it never falls back to wall-clock time. A `TransferCoordinator` may set the clock to a supplied `to_iso8601` instant; the response echoes the new position as `current_utc`. Moving the clock does not eagerly rewrite anything: lazy bed-hold expiries and diversion `effective_status` re-derive from the new clock position on subsequent reads and writes that touch those resources.

### 2.5. Common Resource Properties

Most resources share a standard system-managed envelope of four fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation.
- `version` (integer): a system-managed counter that increments by exactly 1 on every mutation of the resource.

Three resources are append-only records and carry a reduced envelope: a `PhysicianCommunication`, a `RefusalRecord`, and a `TransferOutcome` each have only `id` and `created_at` — both `updated_at` and `version` are absent from them. Every mutation of a versioned resource, including server-initiated cascades such as a hold expiring or a case being kicked back to `INTAKE` by a screening amendment, updates that resource's `updated_at` and increments its `version`.

### 2.6. Bed Occupancy Accounting and the Saturation Hysteresis

Each facility's load is described by three computed figures. `operational_bed_count` counts the facility's beds whose status is anything other than `OUT_OF_SERVICE`. `unavailable_bed_count` counts beds in `HELD` or `OCCUPIED`. `occupancy_pct` is the unavailable count divided by the operational count, multiplied by 100, and rounded half-up to two decimal places; when a facility has no operational beds at all, `occupancy_pct` is defined as 100.0. These figures are recomputed after every bed status change — hold creation, confirmation, release, or expiry, and every housekeeping status update.

Immediately after every occupancy recompute, a saturation rule runs with a deliberate hysteresis band. When `occupancy_pct` reaches 95.0 or more — exactly 95.00 triggers — and the facility has no `ACTIVE` diversion event scoped `ALL_UNITS`, the system auto-creates a `DiversionEvent` with scope `ALL_UNITS`, a window starting at the current clock and ending four hours later, the reason `AUTO_OCCUPANCY_SATURATION`, and `auto_created` set to true. When `occupancy_pct` falls strictly below 90.0 — a reading of exactly 90.00 does not lift anything — every auto-created, `ACTIVE`, `ALL_UNITS` diversion of the facility is lifted at the current clock. Inside the band from 90.0 up to but not including 95.0, the rule makes no automatic change in either direction. A newly registered facility, having zero beds, starts with `diversion_status` `OPEN`, both bed counts at 0, and `occupancy_pct` 100.0 — the saturation rule's entry condition is checked against the no-active-`ALL_UNITS`-event guard, so occupancy alone never stacks a second auto-diversion on an existing one.

### 2.7. Diversion Windows and Closed-Interval Semantics

A diversion window is a closed interval: it occupies its `starts_at` through its `ends_at` inclusive of both endpoints. A new window's `ends_at` must be strictly later than its `starts_at`, and a window whose endpoints merely touch an existing window of the same facility — the new `starts_at` equal to an existing `ends_at`, or the new `ends_at` equal to an existing `starts_at` — counts as overlapping. New diversion windows must be strictly disjoint from every existing `SCHEDULED` or `ACTIVE` event of the same facility; a touch or overlap is rejected with `ERR_DIVERSION_OVERLAP`.

A diversion event's `effective_status` is never stored; it is derived from the logical clock on every read. It reads `LIFTED` once `lifted_at` is set; otherwise `EXPIRED` once the clock has reached `ends_at`; otherwise `ACTIVE` once the clock has reached `starts_at`; otherwise `SCHEDULED`. The facility-level `diversion_status` is then a roll-up of its events: `HARD_DIVERSION` when any of the facility's events is `ACTIVE` with scope `ALL_UNITS`; `SOFT_DIVERSION` when any event is `ACTIVE` with scope `SPECIFIC_UNIT` and none is `ACTIVE` with scope `ALL_UNITS`; otherwise `OPEN`.

### 2.8. Validation Precedence and Existence Checking

A request that fails several rules must fail with the earliest rule on a fixed ladder; the ordering is part of the contract. Evaluated in order, the rungs are:

1. **User context** — `X-User-ID` and `X-User-Role` present, role declared (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. **Role authorization** — the role is listed for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`, 403).
3. **Request-body schema** — required fields present, types correct, enum members valid, minimum lengths met (a refusal `narrative` of at least 50 characters, review `findings` of at least 30 characters), `ends_at` strictly after `starts_at`, `distance_miles` greater than 0, `required_documents` non-empty, and a diversion `unit_type` present exactly when `scope` is `SPECIFIC_UNIT` and forbidden otherwise (`ERR_INVALID_REQUEST`, `ERR_NARRATIVE_TOO_SHORT`, `ERR_FINDINGS_TOO_SHORT`; all 400).
4. **Existence** — path-template identifiers validated left to right, so the first missing id in the path produces its own 404, and body foreign keys such as `bed_id`, `receiving_facility_id`, `receiving_physician_id`, `sending_physician_id`, and `sending_facility_id` must exist (`ERR_FACILITY_NOT_FOUND`, `ERR_PHYSICIAN_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_BED_NOT_FOUND`, `ERR_SCREENING_NOT_FOUND`, `ERR_COMMUNICATION_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, `ERR_PACKET_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_DIVERSION_NOT_FOUND`; all 404).
5. **Entity-backed identity** — the `X-User-ID` comparisons of §2.1 (`ERR_NOT_CASE_PHYSICIAN`, `ERR_NOT_FACILITY_MANAGER`, `ERR_REVIEWER_CONFLICT_OF_INTEREST`, `ERR_NOT_REVIEWER`; all 403).
6. **Optimistic concurrency** — the expected-version field matches the parent's current `version` (`ERR_STALE_VERSION`, 412).
7. **State preconditions** — correct from-state and singleton guards (`ERR_INVALID_STATE`, `ERR_SCREENING_LOCKED`, `ERR_DUPLICATE_SCREENING`, `ERR_DUPLICATE_PACKET`, `ERR_DUPLICATE_NOTIFICATION`, `ERR_BED_NOT_AVAILABLE`, `ERR_HOLD_NOT_ACTIVE`, `ERR_DISPATCH_NOT_CANCELLABLE`; all 409).
8. **Clinical and regulatory safety** — diversion, capability, crew, distance, certification, isolation (`ERR_FACILITY_ON_DIVERSION` at 403; `ERR_CAPABILITY_MISMATCH`, `ERR_CREW_CAPABILITY_INSUFFICIENT`, `ERR_AIR_DISTANCE_BELOW_MINIMUM`, `ERR_CERTIFICATION_INSUFFICIENT`, `ERR_ISOLATION_REQUIRED` at 422).
9. **Selector empty pool** — acceptance with no eligible bed (`ERR_NO_ELIGIBLE_BED`, 409).
10. **Cross-referential integrity** — same-facility, physician-facility, bed-facility, bed-unit, packet-readiness (`ERR_SAME_FACILITY_TRANSFER` at 400; `ERR_PHYSICIAN_FACILITY_MISMATCH`, `ERR_BED_FACILITY_MISMATCH`, `ERR_BED_UNIT_MISMATCH` at 422; `ERR_PACKET_INCOMPLETE` at 409).
11. **Temporal rules** — hold expiry at dispatch, diversion overlap (`ERR_BED_HOLD_EXPIRED`, `ERR_DIVERSION_OVERLAP`; both 409).
12. **Payer clearance** — dispatch without a cleared notification (`ERR_INSURANCE_NOT_CLEARED`, 402).

For nested paths — a screening under a case, beds under a facility — rung 4's left-to-right rule means a missing parent surfaces before the child is ever examined. Where a single operation carries several checks from different rungs, the rung order decides which error the caller sees: at dispatch, for instance, an inadequate crew surfaces before an incomplete packet, which surfaces before an expired hold, which in turn surfaces before a missing payer clearance.

### 2.9. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency. Manually placing a bed hold against a case requires a non-optional `expected_transfer_case_version` field carrying the `TransferCase` `version` the client last observed; if the case's current `version` has advanced since, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Because a successful hold creation supersedes any prior active hold and bumps the case version, a client holding a pre-supersede version is writing against a stale case view. Appending documents to a clinical packet likewise requires a non-optional `expected_clinical_packet_version` matching the packet's current `version`, with the same `ERR_STALE_VERSION` (HTTP 412) on mismatch; each successful upload bumps the packet version, so a stale expectation means the client merged against an outdated document set. Endpoints not named here take no version field.

### 2.10. Numeric Precision, Rounding, and Time Arithmetic

Percentages — `occupancy_pct` — are rounded half-up to two decimal places. Quality-review dimension scores are stored rounded half-up to zero decimal places, and the composite score is rounded half-up to two decimal places; §3.9 pins the rounding order. Refusal risk scores are integers. Durations and estimates are integer minutes: base transport times and the conservative inflation round up to a whole minute, while realized durations are the elapsed seconds between two clock readings divided by 60 and rounded down to a whole minute.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Facilities, Beds, and Physicians

A `TransferCoordinator` registers a facility with a display `name`, a `facility_code` that must be unique across all facilities, a `trauma_level` of `LEVEL_1`, `LEVEL_2`, `LEVEL_3`, `COMMUNITY`, or `CRITICAL_ACCESS`, and a `capabilities` array listing services the facility offers, such as `CARDIAC_CATH`, `NICU`, `BURN`, `STROKE`, or `TRAUMA`. Physicians are registered the same way with a `full_name`, the `facility_id` of their home facility, a `specialty` of `EMERGENCY`, `CARDIOLOGY`, `NEUROLOGY`, `SURGERY`, `INTENSIVIST`, `PEDIATRICS`, or `GENERAL`, and an `is_on_call` flag that defaults to true. Reading a facility returns its computed occupancy block alongside the registered fields; its beds, its physicians, and its diversion events are listed through dedicated collection reads, the bed listing optionally filtered by `status` or `unit_type`.

Bed inventory is managed by the `BedManager` of the facility in question: registering a bed takes a facility-local `bed_code` such as ICU-04, a `unit_type` of `ICU`, `CVICU`, `NICU`, `PICU`, `TELEMETRY`, `MED_SURG`, `BURN`, or `ED_HOLD`, and an optional `isolation_capable` flag defaulting to false; the bed starts life `AVAILABLE`. The caller's `X-User-ID` must equal the facility's `id`, or the registration is rejected with `ERR_NOT_FACILITY_MANAGER`. Housekeeping status changes move a bed among `AVAILABLE`, `OCCUPIED`, and `OUT_OF_SERVICE` — specifically `AVAILABLE` to and from `OCCUPIED`, `AVAILABLE` to `OUT_OF_SERVICE`, `OCCUPIED` to `OUT_OF_SERVICE`, and `OUT_OF_SERVICE` back to `AVAILABLE`. `HELD` is never a legal housekeeping input, and a bed currently `HELD` rejects the housekeeping update outright with `ERR_INVALID_STATE`: only the bed-hold lifecycle of §3.4 may move a bed into or out of `HELD`. Every one of these flips triggers the occupancy recompute and saturation evaluation of §2.6.

Declaring a diversion is also a `BedManager` duty, with a `scope` of `ALL_UNITS` or `SPECIFIC_UNIT`; a `unit_type` accompanies exactly the `SPECIFIC_UNIT` scope, plus `starts_at` and `ends_at` bracketing the window and a free-text `reason`. The closed-interval disjointness rule of §2.7 applies at declaration. A `SCHEDULED` or `ACTIVE` diversion can be lifted early — manually by the facility's `BedManager`, whose `X-User-ID` must equal the event's `facility_id`, or automatically by the saturation rule — which stamps `lifted_at` and recomputes the facility's `diversion_status`.

### 3.2. Opening a Case and the EMTALA Screening Loop

A transfer begins when a `TransferCoordinator` opens a case with a de-identified `patient_ref` token, the `sending_facility_id`, the responsible `sending_physician_id`, an `acuity_level` of `CRITICAL`, `EMERGENT`, `URGENT`, or `STABLE`, the `required_unit_type` the receiving bed must have, a `requires_isolation` flag defaulting to false, and the `required_capability` string the receiving facility must list. The named physician must belong to the named facility, or creation fails with `ERR_PHYSICIAN_FACILITY_MISMATCH`. A new case sits in `INTAKE` with `negotiation_round` 0, `emtala_obligation` `UNDETERMINED`, `emtala_determined_at` null, `active_bed_hold_id` null, both receiving references null, and `refusal_count` 0. Cases can be listed and filtered by `status`, `sending_facility_id`, `receiving_facility_id`, `sending_physician_id`, or `receiving_physician_id`.

Before anything else can happen, the sending physician documents the EMTALA position. The physician whose `X-User-ID` equals the case's `sending_physician_id` creates the case's screening — exactly one per case, a second attempt drawing `ERR_DUPLICATE_SCREENING` — recording `has_emergency_medical_condition`, `is_stabilized`, an optional `benefits_outweigh_risks` defaulting to false, and an optional `physician_certification` narrative defaulting to empty. The screening's `determination` is computed, not chosen: `EMTALA_NOT_APPLIES` when there is no emergency medical condition, `EMTALA_APPLIES` when one exists and the patient is stabilized, and `EMERGENCY_EXCEPTION` when one exists and the patient is not stabilized. The screening is born in `DRAFT`.

Certification is the act that moves the case forward. Certifying requires the case in `INTAKE`, the screening present (certifying before creation fails with `ERR_SCREENING_NOT_FOUND`), the screening in `DRAFT` or `AMENDED`, and the caller to be the case's sending physician (`ERR_NOT_CASE_PHYSICIAN`). When the determination would be `EMERGENCY_EXCEPTION`, two further conditions must hold: `benefits_outweigh_risks` must be true and `physician_certification` must run to at least 30 characters; otherwise certification is refused with `ERR_CERTIFICATION_INSUFFICIENT`. A successful certification flips the screening to `CERTIFIED` with `certified_at` stamped from the clock, mirrors the `determination` onto the case's `emtala_obligation`, stamps the case's `emtala_determined_at`, advances the case `INTAKE → EMTALA_DETERMINED`, and bumps the case version.

A certification can be walked back exactly once per cycle. Amending applies new values for any of `has_emergency_medical_condition`, `is_stabilized`, `benefits_outweigh_risks`, or `physician_certification`, flips the screening `CERTIFIED → AMENDED`, increments its `amendment_count`, reverts the case `EMTALA_DETERMINED → INTAKE`, resets `emtala_obligation` to `UNDETERMINED`, clears `emtala_determined_at` to null, and bumps the case version. Amendment is only possible while the case sits in `EMTALA_DETERMINED`: once the case has advanced past it, the screening is locked and amending draws `ERR_SCREENING_LOCKED`, while amending a case back in `INTAKE` — or a screening not currently `CERTIFIED` — draws `ERR_INVALID_STATE`. Re-certification after amendment simply replays the `INTAKE → EMTALA_DETERMINED` path with the amended values.

### 3.3. Negotiating Acceptance: Requests, Refusals, and Re-Requests

With the obligation determined, a `TransferCoordinator` shops the case. Requesting acceptance addresses the case to a receiving facility and physician via a payload carrying `receiving_facility_id`, `receiving_physician_id`, a `contact_method` of `PHONE`, `SECURE_MESSAGE`, or `TELEMEDICINE`, and optional `notes`. The case must be `EMTALA_DETERMINED`. The checks run in the ladder order of §2.8: both identifiers must exist; the receiving facility must list the case's `required_capability` among its capabilities, failing with `ERR_CAPABILITY_MISMATCH`; then cross-referential rules fire — the receiving facility must differ from the sending facility (`ERR_SAME_FACILITY_TRANSFER`) and the named physician's home facility must be the receiving facility (`ERR_PHYSICIAN_FACILITY_MISMATCH`). A valid request opens a negotiation round: a `PhysicianCommunication` is created in `PENDING` with `from_physician_id` set to the case's sending physician, `to_physician_id` to the addressed receiving physician, `round` set to the case's `negotiation_round` plus one, and the `contact_method` and `notes` recorded; the case stores the receiving references, increments `negotiation_round`, bumps its version, and moves `EMTALA_DETERMINED → AWAITING_ACCEPTANCE`.

Refusal is documented, not silent. The receiving physician — `X-User-ID` equal to the case's `receiving_physician_id` — refuses by supplying a `refusal_category` of `NO_BED_AVAILABLE`, `CAPABILITY_UNAVAILABLE`, `DIVERSION_ACTIVE`, `UNSTABLE_FOR_TRANSFER`, or `CAPACITY_EXCEEDED`, plus a `narrative` of at least 50 characters (`ERR_NARRATIVE_TOO_SHORT`). The current round's communication flips `PENDING → REFUSED` with `responded_at` stamped; a `RefusalRecord` is created capturing the refusing `facility_id`, the `refusing_physician_id`, the category and narrative, and the `round` in which it occurred; the case's `refusal_count` — the count of its refusal records — is recomputed, its version bumps, and it moves `AWAITING_ACCEPTANCE → REFUSED`.

Every refusal is scored for EMTALA exposure at creation. The `emtala_risk_score` starts from a category base — 30 for `NO_BED_AVAILABLE`, 25 for `CAPABILITY_UNAVAILABLE`, 40 for `DIVERSION_ACTIVE`, 10 for `UNSTABLE_FOR_TRANSFER`, 20 for `CAPACITY_EXCEEDED` — adds an obligation increment of 50 when the case is `EMTALA_APPLIES`, 20 under `EMERGENCY_EXCEPTION`, and 0 under `EMTALA_NOT_APPLIES` or `UNDETERMINED`, then adds 10 points per prior refusal of the same case, counting at most three priors. The `emtala_risk_flag` bands the score: `HIGH` at 70 or more — exactly 70 is `HIGH` — `ELEVATED` from 40 up to but not including 70, and `LOW` below 40. Refusing a case whose `emtala_obligation` is `EMTALA_APPLIES` also auto-opens a `QualityReview` with trigger `REFUSAL_RISK` in `OPEN`, but only when the case has no review already `OPEN` or `UNDER_REVIEW`. Refusal records can be listed and filtered by `transfer_case_id`, `facility_id`, or `refusing_physician_id`; reading a single record by an unknown id fails with `ERR_REFUSAL_RECORD_NOT_FOUND`.

`REFUSED` is not terminal. A `TransferCoordinator` may re-request, addressing the case to a new `receiving_facility_id` and `receiving_physician_id` with a fresh `contact_method` and `notes`; the same existence, capability, same-facility, and physician-facility checks are evaluated against the new values. A new communication opens in `PENDING` for the incremented `negotiation_round`, the receiving references are overwritten, and the case returns `REFUSED → AWAITING_ACCEPTANCE`. The loop may iterate any number of times. Communications are readable as a collection, filterable by `transfer_case_id`, `from_physician_id`, or `to_physician_id`.

### 3.4. Securing a Bed: Selector, Holds, and Expiry

Acceptance is the receiving physician's counterpart to refusal and takes only optional `notes`. The case must be `AWAITING_ACCEPTANCE` and the caller the case's receiving physician. Two safety gates then apply in ladder order: the receiving facility must not sit under an applicable diversion — an `ACTIVE` event scoped `ALL_UNITS`, or one scoped `SPECIFIC_UNIT` whose `unit_type` matches the case's `required_unit_type`, failing with `ERR_FACILITY_ON_DIVERSION` — and the bed selector must find an eligible bed, failing with `ERR_NO_ELIGIBLE_BED`.

The selector runs over all beds of the receiving facility. A bed is eligible when it belongs to the receiving facility, is `AVAILABLE`, matches the case's `required_unit_type`, and — when the case's `requires_isolation` is true — is `isolation_capable`. Eligible beds are ranked by isolation preservation first (when the case does not require isolation, beds that are not isolation-capable rank ahead of those that are, keeping isolation capacity free), then by `created_at` ascending so the oldest bed wins, and finally by `bed_code` ascending in lexicographic order as the tie-break. An empty pool rejects the acceptance with `ERR_NO_ELIGIBLE_BED`.

A successful acceptance flips the round's communication `PENDING → ACCEPTED` with `responded_at` stamped, moves the selected bed `AVAILABLE → HELD`, and creates a `BedHold` in `ACTIVE` with `hold_started_at` stamped from the clock and `hold_expires_at` computed from the case's acuity: sixty minutes for `CRITICAL`, two hours for `EMERGENT`, four hours for `URGENT`, and eight hours for `STABLE`. The case records the hold in `active_bed_hold_id`, moves `AWAITING_ACCEPTANCE → ACCEPTED`, and bumps its version; the receiving facility's occupancy recomputes and the saturation rule evaluates.

A hold occupies its bed over a half-open interval — from `hold_started_at` up to but not including `hold_expires_at`; when the clock reaches the expiry instant exactly, the hold no longer blocks. Expiry is lazy: any read or write that touches an `ACTIVE` hold while the clock is at or past `hold_expires_at` flips it to `EXPIRED` with `release_reason` `EXPIRED`, returns the bed `HELD → AVAILABLE`, clears the case's `active_bed_hold_id`, bumps the case version, and recomputes occupancy. Holds of cases that have left `ACCEPTED` never expire this way. A facility's `BedManager` may instead release an `ACTIVE` hold manually — the hold must be `ACTIVE` (`ERR_HOLD_NOT_ACTIVE`), the case still `ACCEPTED` (`ERR_INVALID_STATE`), and the caller's `X-User-ID` equal to the held bed's `facility_id` (`ERR_NOT_FACILITY_MANAGER`) — which stamps `release_reason` `MANUAL`, frees the bed, clears `active_bed_hold_id`, and recomputes occupancy. Holds are listable, filterable by `bed_id`, `transfer_case_id`, or `status`, and reading a single hold applies lazy expiry before answering.

Manual placement exists for re-placement after expiry or selector override. A `BedManager` places a hold on a specific bed by supplying `bed_id` together with the `expected_transfer_case_version` guard of §2.9. The caller's `X-User-ID` must equal the case's `receiving_facility_id`, the case must be `ACCEPTED`, the bed must exist, belong to the case's receiving facility (`ERR_BED_FACILITY_MISMATCH`), match the case's `required_unit_type` (`ERR_BED_UNIT_MISMATCH`), be `AVAILABLE` (`ERR_BED_NOT_AVAILABLE`), and be isolation-capable when the case requires isolation (`ERR_ISOLATION_REQUIRED`). Success supersedes any prior `ACTIVE` hold of the case — the old hold flips to `RELEASED` with `release_reason` `SUPERSEDED` and its bed returns to `AVAILABLE` — moves the new bed to `HELD`, creates the new `ACTIVE` hold with the same acuity-scaled expiry math, bumps the case version, and recomputes occupancy.

### 3.5. The Clinical Packet and Imaging Exchange

The sending physician assembles the paperwork. Creating the case's clinical packet — again a singleton, a second attempt drawing `ERR_DUPLICATE_PACKET`, and again requiring `X-User-ID` to equal the case's `sending_physician_id` — takes a non-empty `required_documents` array drawn from `H_AND_P`, `LABS`, `MED_RECONCILIATION`, `CODE_STATUS`, `CONSENT`, and `TRANSFER_CERT`, plus an optional `imaging_studies` array of study reference and modality pairs the receiving facility requires. The packet starts with empty `received_documents` and `exchanged_study_refs`.

Three computed statuses track readiness. `document_status` reads `DOCUMENTS_COMPLETE` when every code in `required_documents` appears in `received_documents`, otherwise `INCOMPLETE`. `imaging_status` reads `IMAGING_COMPLETE` when every study reference in `imaging_studies` appears in `exchanged_study_refs` — vacuously true when no studies are required — otherwise `IMAGING_PENDING`. `overall_status` is `READY` only when both are complete, otherwise `INCOMPLETE`.

Documents accumulate union-only. The sending physician appends a batch via a `documents` array guarded by `expected_clinical_packet_version` per §2.9; duplicates already received are ignored, the packet version bumps, and the statuses recompute. Imaging confirmation works the same way without a version guard: the sending physician supplies the `exchanged_study_refs` confirmed exchanged, the set unions, the version bumps, and `imaging_status` and `overall_status` recompute. Packets are listable, filterable by `transfer_case_id`.

### 3.6. Payer Notification and the Emergency Exception

Once a case is past `INTAKE` and not yet terminal, a `TransferCoordinator` opens its insurance notification with a `payer_id` and a `channel` of `PORTAL`, `PHONE`, or `FAX`. A case carries at most one non-`VOIDED` notification; a second live attempt fails with `ERR_DUPLICATE_NOTIFICATION`, and opening one while the case is still in `INTAKE` or already terminal fails with `ERR_INVALID_STATE`. The notification is born `PENDING` with `notified_at` null and `is_late` false.

The deadline is derived from the EMTALA position. `sla_due_at` is the case's `emtala_determined_at` plus sixty minutes when the obligation is `EMTALA_APPLIES`, sixty minutes under `EMERGENCY_EXCEPTION`, and two hundred forty minutes under `EMTALA_NOT_APPLIES`. Marking the payer notified flips `PENDING → NOTIFIED`, stamps `notified_at` from the clock, and recomputes `is_late`: true only when a `NOTIFIED` notification's `notified_at` is strictly later than `sla_due_at` — a notification landing exactly at the deadline is on time — and false for every other status. When prior notification is not feasible, the coordinator instead claims the emergency exception, flipping `PENDING → EXCEPTION_CLAIMED`, recording an `exception_reason` of `UNSTABLE_EMC`, `NO_PAYER_IDENTIFIABLE`, or `CLINICAL_URGENCY`, and forcing `is_late` to false. Notifications are listable, filterable by `transfer_case_id` or `status`.

### 3.7. Transport: Dispatch, Departure, and Arrival

Arranging transport is the densest gate in the workflow, and its checks fire in the ladder order of §2.8: state first, then crew, then distance, then packet, then hold, then payer. The case must be `ACCEPTED`. The dispatch payload carries a `mode` of `GROUND_BLS`, `GROUND_ALS`, `AIR_ROTOR`, or `AIR_FIXED_WING`, a `crew_capability` of `BLS`, `ALS`, `CCT`, or `CRITICAL_CARE` — ordered in that sequence from least to most capable — and a `distance_miles` that must be greater than 0. Crew capability must meet the acuity minimum: `CRITICAL` demands `CCT`, `EMERGENT` demands `ALS`, and `URGENT` or `STABLE` demand `BLS`; anything short fails with `ERR_CREW_CAPABILITY_INSUFFICIENT`. Air modes carry distance floors — `AIR_ROTOR` requires at least 30 miles and `AIR_FIXED_WING` at least 100 — failing with `ERR_AIR_DISTANCE_BELOW_MINIMUM`. The case's clinical packet must exist with `overall_status` `READY`, failing with `ERR_PACKET_INCOMPLETE` (which also fires when no packet exists at all). The case's active hold must still be within its window — a hold whose `hold_expires_at` is at or before the clock flips to `EXPIRED` and the dispatch fails with `ERR_BED_HOLD_EXPIRED`. Finally, a notification in `NOTIFIED` or `EXCEPTION_CLAIMED` must exist, failing with `ERR_INSURANCE_NOT_CLEARED`.

A valid dispatch creates a `TransportDispatch` in `DISPATCHED` with `dispatched_at` stamped, both estimated durations computed, and the case advanced `ACCEPTED → TRANSPORT_ARRANGED`. The estimate works from a base of the distance divided by the mode's cruise speed — 40 miles per hour for `GROUND_BLS`, 45 for `GROUND_ALS`, 120 for `AIR_ROTOR`, 160 for `AIR_FIXED_WING` — converted to minutes and rounded up to a whole minute. `estimated_minutes_optimistic` is that base plus a mode overhead of 10 minutes for either ground mode, 25 for rotor, 45 for fixed wing. `estimated_minutes_conservative` inflates the base by a quarter and rounds up before adding the same mode overhead, a crew buffer of 0 for `BLS` or `ALS`, 10 for `CCT`, and 15 for `CRITICAL_CARE`, and a further 10 minutes when the case acuity is `CRITICAL`. The conservative figure is therefore never below the optimistic one, and strictly above it whenever any buffer applies.

Departure and arrival are separate clocked events. Departing requires the case in `TRANSPORT_ARRANGED` and its latest dispatch still `DISPATCHED`; it flips the dispatch `DISPATCHED → EN_ROUTE`, stamps `departed_at`, moves the case `TRANSPORT_ARRANGED → EN_ROUTE`, and bumps the case version. A dispatch that has not yet departed can be cancelled instead — only a `DISPATCHED` transport is cancellable, anything else drawing `ERR_DISPATCH_NOT_CANCELLABLE` — which flips it to `CANCELLED` and reverts the case `TRANSPORT_ARRANGED → ACCEPTED` so a different mode or crew can be arranged. Arrival requires the case in `EN_ROUTE` with its active dispatch `EN_ROUTE`; it stamps `arrived_at`, flips the dispatch to `ARRIVED`, and computes `actual_duration_minutes` as the elapsed seconds between `departed_at` and `arrived_at` divided by 60 and rounded down — the operational wheels-rolling measurement, always strictly smaller than the clinical-intent measurement of §3.8 whenever departure lagged determination. Dispatches are listable, filterable by `transfer_case_id` or `status`.

### 3.8. Arrival Outcomes, Completion, and Cancellation Compensation

Arrival is the workflow's biggest cascade. Beyond the dispatch bookkeeping of §3.7, arriving flips the case's `ACTIVE` hold to `CONFIRMED` with `release_reason` `ARRIVAL_CONFIRMED`, and that confirmation flips the held bed `HELD → OCCUPIED`, recomputing the receiving facility's occupancy and evaluating saturation. It then creates the case's `TransferOutcome` — exactly one per case — recording the supplied `arrival_condition` of `STABLE`, `DETERIORATED`, or `CRITICAL_DECLINE`, the `deterioration_en_route` flag, whether the receiving physician `receiving_physician_confirmed` the arrival condition, and a `recorded_at` stamp. The outcome's `door_to_arrival_minutes` is the clinical-intent duration: elapsed seconds between the case's `emtala_determined_at` and the arrival instant, divided by 60, rounded down. When `deterioration_en_route` is true and no review is already `OPEN` or `UNDER_REVIEW`, a `QualityReview` with trigger `DETERIORATION` opens automatically. The case retains its `active_bed_hold_id` for audit, moves `EN_ROUTE → ARRIVED`, and bumps its version.

Completing the case is the administrative close: from `ARRIVED`, it ensures a routine review exists — creating a `QualityReview` with trigger `ROUTINE` in `OPEN` when none is `OPEN` or `UNDER_REVIEW` — and moves the case `ARRIVED → COMPLETED`. A case's outcome is readable as a collection of length zero or one.

Cancellation unwinds. From any of `INTAKE`, `EMTALA_DETERMINED`, `AWAITING_ACCEPTANCE`, `REFUSED`, `ACCEPTED`, or `TRANSPORT_ARRANGED` — anything else draws `ERR_INVALID_STATE` — a `TransferCoordinator` cancels with a `cancel_reason`, and the system compensates every entity that exists: an `ACTIVE` hold flips to `RELEASED` with `release_reason` `CASE_CANCELLED`, freeing its bed `HELD → AVAILABLE` with the usual occupancy recompute and saturation evaluation; a notification in `PENDING`, `NOTIFIED`, or `EXCEPTION_CLAIMED` flips to `VOIDED`; a `DISPATCHED` transport flips to `CANCELLED`; a `PENDING` communication flips to `VOIDED`; and the case lands in `CANCELLED` with its version bumped. `COMPLETED` and `CANCELLED` are the case's terminal states.

### 3.9. Quality Review and Scoring

Reviews enforce segregation of duties. Every review records its `trigger` — `ROUTINE` when auto-created at completion, `REFUSAL_RISK` at a refusal of an `EMTALA_APPLIES` case, or `DETERIORATION` at an arrival with en-route deterioration. Beginning a review requires it `OPEN` and assigns the calling `QualityReviewer` by stamping `reviewer_physician_id` from `X-User-ID` — but a caller who is the case's sending or receiving physician is rejected with `ERR_REVIEWER_CONFLICT_OF_INTEREST`. The review moves `OPEN → UNDER_REVIEW`. Closing requires the review `UNDER_REVIEW`, the caller to be the assigned reviewer (`ERR_NOT_REVIEWER`), `findings` of at least 30 characters (`ERR_FINDINGS_TOO_SHORT`), and an `outcome` of `CONCURRENCE`, `MINOR_VARIANCE`, `MAJOR_VARIANCE`, or `SENTINEL_EVENT`. Closing computes all four scores and moves the review to `CLOSED`. Reviews are listable, filterable by `transfer_case_id`, `reviewer_physician_id`, or `status`.

The scoring math is pinned, rounding order included. `timeliness_score` starts at 100 and sheds a quarter point for every minute the case's `door_to_arrival_minutes` ran past a four-hour target, floored at 0 — and is 0 outright when the case never produced an outcome. `documentation_score` is the percentage of the packet's `required_documents` present in `received_documents` — 100 times the size of the intersection divided by the size of `required_documents` — defined as 100 when no documents were required and 0 when no packet exists. `protocol_score` starts at 100, deducts 20 per refusal on the case, 30 when any of the case's notifications is `is_late`, and 40 when any of the case's holds ended `EXPIRED`, floored at 0. Each of the three dimensions is first rounded half-up to zero decimal places and stored in that rounded integer form; only then is `composite_score` computed as the weighted sum of the stored integers — 40 percent timeliness, 35 percent documentation, 25 percent protocol — rounded half-up to two decimal places. Weighting the unrounded dimensions and rounding once is a different calculation and is not the specified behavior.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Request payloads, preconditions, and side effects for each operation are specified in §3; the table below is the routing contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | TransferCoordinator |
| POST | `/facilities` | Register a facility | TransferCoordinator |
| GET | `/facilities/{id}` | Get a facility including computed occupancy fields | Any |
| GET | `/facilities/{id}/beds` | List beds of a facility | Any |
| GET | `/facilities/{id}/physicians` | List physicians of a facility | Any |
| GET | `/facilities/{id}/diversion-events` | List diversion events of a facility | Any |
| POST | `/facilities/{id}/beds` | Register a bed at a facility | BedManager |
| PUT | `/beds/{id}` | Housekeeping status change among AVAILABLE / OCCUPIED / OUT_OF_SERVICE | BedManager |
| POST | `/physicians` | Register a physician | TransferCoordinator |
| POST | `/facilities/{id}/diversion-events` | Declare a diversion window | BedManager |
| POST | `/diversion-events/{id}/lift` | Manually lift a SCHEDULED or ACTIVE diversion | BedManager |
| POST | `/transfer-cases` | Open a transfer case | TransferCoordinator |
| GET | `/transfer-cases` | List and filter transfer cases | Any |
| GET | `/transfer-cases/{id}` | Get a transfer case | Any |
| POST | `/transfer-cases/{id}/emtala-screening` | Create the case's EMTALA screening (singleton) | SendingPhysician |
| GET | `/transfer-cases/{id}/emtala-screening` | Get the case's screening (array of length 0 or 1) | Any |
| POST | `/transfer-cases/{id}/emtala-screening/certify` | Certify the screening | SendingPhysician |
| POST | `/transfer-cases/{id}/emtala-screening/amend` | Amend a certified screening | SendingPhysician |
| POST | `/transfer-cases/{id}/request-acceptance` | Address the case to a receiving facility and physician | TransferCoordinator |
| POST | `/transfer-cases/{id}/re-request` | After refusal, address a new receiving facility and physician | TransferCoordinator |
| POST | `/transfer-cases/{id}/accept` | Receiving physician accepts; bed selector runs | ReceivingPhysician |
| POST | `/transfer-cases/{id}/refuse` | Receiving physician refuses with category and narrative | ReceivingPhysician |
| GET | `/communications` | List physician communications | Any |
| GET | `/communications/{id}` | Get a physician communication | Any |
| POST | `/transfer-cases/{id}/bed-holds` | Manually place a hold on a specific bed (OCC-guarded) | BedManager |
| GET | `/bed-holds` | List bed holds | Any |
| GET | `/bed-holds/{id}` | Get a bed hold (lazy expiry applied) | Any |
| POST | `/bed-holds/{id}/release` | Manually release an ACTIVE hold | BedManager |
| POST | `/transfer-cases/{id}/dispatch` | Arrange transport; computes both ETT variants | TransferCoordinator |
| GET | `/transport-dispatches` | List transport dispatches | Any |
| GET | `/transport-dispatches/{id}` | Get a transport dispatch | Any |
| POST | `/transport-dispatches/{id}/cancel` | Cancel a DISPATCHED transport | TransferCoordinator |
| POST | `/transfer-cases/{id}/depart` | Patient departs the sending facility | TransferCoordinator |
| POST | `/transfer-cases/{id}/arrive` | Patient arrives; confirms the hold and records the outcome | TransferCoordinator |
| POST | `/transfer-cases/{id}/complete` | Close the transfer administratively | TransferCoordinator |
| POST | `/transfer-cases/{id}/cancel` | Cancel the case with full compensation | TransferCoordinator |
| GET | `/transfer-cases/{id}/outcome` | Get the case's TransferOutcome (array of length 0 or 1) | Any |
| POST | `/transfer-cases/{id}/insurance-notifications` | Create the case's insurance notification | TransferCoordinator |
| GET | `/insurance-notifications` | List insurance notifications | Any |
| GET | `/insurance-notifications/{id}` | Get an insurance notification | Any |
| POST | `/insurance-notifications/{id}/notify` | Mark the payer notified | TransferCoordinator |
| POST | `/insurance-notifications/{id}/claim-exception` | Claim the emergency exception | TransferCoordinator |
| POST | `/transfer-cases/{id}/clinical-packet` | Create the case's clinical packet (singleton) | SendingPhysician |
| GET | `/clinical-packets` | List clinical packets | Any |
| GET | `/clinical-packets/{id}` | Get a clinical packet | Any |
| POST | `/clinical-packets/{id}/documents` | Append received documents (union-only, OCC-guarded) | SendingPhysician |
| POST | `/clinical-packets/{id}/imaging-exchange` | Confirm imaging studies exchanged | SendingPhysician |
| GET | `/refusal-records` | List refusal records | Any |
| GET | `/refusal-records/{id}` | Get a refusal record | Any |
| GET | `/quality-reviews` | List quality reviews | Any |
| GET | `/quality-reviews/{id}` | Get a quality review | Any |
| POST | `/quality-reviews/{id}/begin` | Assign the review to the calling QualityReviewer | QualityReviewer |
| POST | `/quality-reviews/{id}/close` | Close the review with outcome and findings | QualityReviewer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NARRATIVE_TOO_SHORT` | 400 Bad Request |
| `ERR_FINDINGS_TOO_SHORT` | 400 Bad Request |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_PHYSICIAN_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_BED_NOT_FOUND` | 404 Not Found |
| `ERR_SCREENING_NOT_FOUND` | 404 Not Found |
| `ERR_COMMUNICATION_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_DISPATCH_NOT_FOUND` | 404 Not Found |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_PACKET_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_DIVERSION_NOT_FOUND` | 404 Not Found |
| `ERR_REFUSAL_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_CASE_PHYSICIAN` | 403 Forbidden |
| `ERR_NOT_FACILITY_MANAGER` | 403 Forbidden |
| `ERR_NOT_REVIEWER` | 403 Forbidden |
| `ERR_REVIEWER_CONFLICT_OF_INTEREST` | 403 Forbidden |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SCREENING_LOCKED` | 409 Conflict |
| `ERR_DUPLICATE_SCREENING` | 409 Conflict |
| `ERR_DUPLICATE_PACKET` | 409 Conflict |
| `ERR_DUPLICATE_NOTIFICATION` | 409 Conflict |
| `ERR_BED_NOT_AVAILABLE` | 409 Conflict |
| `ERR_HOLD_NOT_ACTIVE` | 409 Conflict |
| `ERR_DISPATCH_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_FACILITY_ON_DIVERSION` | 403 Forbidden |
| `ERR_CAPABILITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREW_CAPABILITY_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_AIR_DISTANCE_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_ISOLATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_BED` | 409 Conflict |
| `ERR_SAME_FACILITY_TRANSFER` | 400 Bad Request |
| `ERR_PHYSICIAN_FACILITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_BED_FACILITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_BED_UNIT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PACKET_INCOMPLETE` | 409 Conflict |
| `ERR_BED_HOLD_EXPIRED` | 409 Conflict |
| `ERR_DIVERSION_OVERLAP` | 409 Conflict |
| `ERR_INSURANCE_NOT_CLEARED` | 402 Payment Required |
