# Medical Examiner Case Management API — Product Requirements Document

## 1. Introduction

A county coroner's office lives at the intersection of forensic science, public health law, and fiscal accountability. From the moment a death is reported, an office must decide whether the case falls within its jurisdiction, assign a manner-of-death investigation lane, take custody of the body, schedule and bill autopsies, chase toxicology results through a documented chain of custody, and — ultimately — put a physician's signature on a death certificate that a family, an insurer, and a court will all rely upon. Each of those steps has a statutory guardrail, and several of them must be performed by *different* people to prevent conflicts of interest.

This document specifies the API that orchestrates that entire lifecycle. The system is first and foremost a **compliance and audit platform**: every state change is deliberate, gated by preconditions, and recorded with an incrementing version so that a stale actor cannot silently overwrite work done by another. Layered on top of that audit spine is a workflow engine that forks each case into distinct investigation lanes, a dual-variant fee calculator that quotes an autopsy at scheduling and re-bills it against real elapsed time at completion, a guarded cooler-inventory subsystem, and a waterfall settlement calculation for indigent burials funded by the county. The requirements below define the contract precisely enough that any conforming implementation will behave identically under the automated test suite.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than a public death report must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. If either header is missing on an operation that requires authentication, or if `X-User-Role` is not one of the roles enumerated below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the declared role is not permitted to perform the requested operation, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes six roles, spelled exactly as follows: `Admin`, `Investigator`, `Pathologist`, `MedicalExaminer`, `LabTech`, and `Anonymous`.

- `Admin` is a system operator that registers actors and cooler units and drives the logical clock. When `X-User-Role` is `Admin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `Investigator`, `X-User-ID` is the `id` of the acting `Investigator` record; ownership checks on any resource that references an `Investigator` compare the resource's foreign-key field to `X-User-ID`. In particular, the lead investigator recorded on a case is matched against `X-User-ID` during property-release segregation-of-duties enforcement.
- When `X-User-Role` is `Pathologist`, `X-User-ID` is the `id` of the acting `Pathologist` record; ownership checks on any resource that references a `Pathologist` (for example, the pathologist assigned to an autopsy exam) compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `MedicalExaminer`, `X-User-ID` is likewise the `id` of the acting `Pathologist` record — a medical examiner is simply a pathologist whose `is_medical_examiner` flag is set. Ownership and segregation checks on any resource referencing a `Pathologist` compare that reference to `X-User-ID`.
- When `X-User-Role` is `LabTech`, `X-User-ID` is an opaque technician identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque reporter identifier not tied to any persisted entity; an anonymous caller may only file a death report and nothing else.

For any role backed by an entity, if `X-User-ID` does not resolve to an existing record of that role's entity type, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Authentication (header presence and role recognition) is evaluated before role authorization, and role authorization is evaluated before entity-identity resolution.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (refreshed on every mutation, same format) and an integer `version` that starts at its initial value and increments by exactly one on each mutation. Every entity in this system — cases, investigators, pathologists, cooler units, bodies, autopsy exams, specimens, tox screens, death certificates, next-of-kin, property items, property releases, and indigent dispositions — carries the full set of `id`, `created_at`, `updated_at`, and `version`.

The `version` field is the audit spine of the platform. Whenever a workflow action mutates a resource — whether directly requested or cascaded automatically as a side effect — that resource's `version` increments and its `updated_at` refreshes. A read-only computed field being recomputed as part of a mutation counts as a mutation for this purpose.

### 2.5. Optimistic Concurrency on Guarded Writes

Two write operations require the client to prove it is acting on a fresh view of a *parent* resource by supplying that parent's last-observed `version`. This is a deliberate serialization point, not a timing race.

When a medical examiner signs a death certificate, the request must carry `expected_case_version` matching the current `version` of the certificate's parent case. If the case's version has advanced since the examiner last read it — for example, because an autopsy completion cascaded a version bump onto the case — the examiner's view of readiness is stale and the sign-off is rejected with `ERR_STALE_VERSION` (HTTP 412) before any state change occurs; the examiner must re-read the case and re-derive readiness.

When an investigator stores a body into a cooler, the request must carry `expected_cooler_version` matching the current `version` of the target cooler unit. If another store or release against that cooler has advanced its version since the client last read it, a slot the client believed free may now be taken, so the stale store is rejected with `ERR_STALE_VERSION` (HTTP 412) before the write. Every other endpoint in the system takes no version field.

### 2.6. Nested Resource Retrieval and Left-to-Right Validation

Many resources are addressed under a parent path — a body under a case, a specimen under a body, a tox screen under a specimen. Whenever a path names more than one resource identifier, the system validates each identifier in strict left-to-right order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the *first* identifier that does not resolve to an existing resource. A specimen requested under a body that does not exist fails on the body before the specimen is ever consulted. This ordering applies equally to creation and action endpoints: the parent's existence is confirmed before any child-scoped or body-specific rule is evaluated.

### 2.7. The Logical Clock

All datetime stamping and every time-gated precondition in this system read from a server-controlled **logical clock** rather than wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to real time. An administrator may advance or rewind the clock to an absolute instant by supplying a `to_iso8601` value; the response reports the new `current_utc`. Fields such as a body's `intake_at` and `released_at`, a specimen's `collected_at`, a certificate's `signed_at`, a case's `closed_at`, and a next-of-kin's `contacted_at` are all stamped from this clock, and autopsy due-time and cooler-occupancy calculations are measured against it.

### 2.8. Jurisdiction, Investigation Lanes, and Required Artifacts

The office serves a configured list of counties. At triage the system decides whether a reported death falls within jurisdiction by matching the case's `death_location_county` against that served-counties configuration, recording the boolean `served_county` and the enumerated `jurisdiction_status` of either `ACCEPTED` or `DECLINED`. Triage also fixes the investigation lane through the `case_type` field, one of `NATURAL`, `ACCIDENT`, `HOMICIDE`, or the initial `PENDING`.

The lane determines whether an autopsy is mandatory before a certificate may be signed. The system derives the boolean `autopsy_required` at triage: it is true for a `HOMICIDE` lane and true for an `ACCIDENT` lane, and false for a `NATURAL` lane (a `PENDING` lane likewise carries no autopsy requirement). This divergence is the heart of the compliance workflow — a homicide or accident case cannot be certified until its autopsy is complete, whereas a natural-death case may proceed directly to sign-off.

### 2.9. Cooler Inventory and Occupancy Accounting

Body storage is a guarded, capacity-limited resource. Each cooler unit publishes a `slot_capacity` (at least 1), a set-point `temperature_c` defaulting to 4, an `out_of_service` flag defaulting to false, and a computed `occupied_slots` count that always equals the number of bodies currently stored in that unit. A store is permitted only when the unit is in service and has a free slot; the occupancy count is recomputed on every store and release so that it never drifts from the true tally of `STORED` bodies pointing at the unit.

The occupancy report for a cooler answers a billing question: how many body-days of storage has it accumulated? For every body currently `STORED` in the unit, the system measures the elapsed time from that body's `intake_at` to the current logical-clock instant and charges one whole day for each started day — that is, the elapsed seconds divided by the number of seconds in a day (86,400), rounded up to the next whole day. A body whose elapsed time is exactly zero (intaken at the current instant) contributes zero days rather than one. The report sums these per-body day counts into `total_body_days` and reports the current `occupied_slots` alongside it.

### 2.10. Fee Precision and Monetary Representation

All fees and monetary amounts in this system are integer cents. The waterfall calculation for indigent dispositions involves only integer inputs and requires no rounding. The autopsy fee calculations remain integer cents throughout, except that when the homicide complexity multiplier introduces a fractional cent the result is rounded to the nearest whole cent using the round-half-up convention. No monetary field is ever represented as a fractional value in a response.

### 2.11. Segregation of Duties

Two steps in the case lifecycle are deliberately assigned to different people to prevent conflicts of interest, and the server enforces this at the moment the second step is attempted. First, the medical examiner who signs a case's death certificate must not be the same pathologist who performed that case's autopsy — a sign-off where the acting examiner's identity equals the case's autopsy pathologist is rejected with `ERR_SEGREGATION_VIOLATION` (HTTP 403). Second, the investigator who approves a property release must not be the lead investigator recorded on the case — an approval where the acting investigator's identity equals the case's lead is rejected with the same `ERR_SEGREGATION_VIOLATION` (HTTP 403).

### 2.12. Validation Ordering

When several checks guard a single operation, they are evaluated in a fixed order so that the most fundamental failure is always the one surfaced. Header presence and role recognition come first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then entity-identity resolution for entity-backed roles (`ERR_FORBIDDEN_ROLE`). Existence of every path- and body-referenced resource is confirmed next, left-to-right, yielding `ERR_NOT_FOUND` on the first miss. Only then are business rules evaluated: state-machine legality (`ERR_INVALID_STATE`), then the operation-specific business constraints described in Section 3, and finally the optimistic-concurrency version check (`ERR_STALE_VERSION`) on the two guarded writes. Malformed request bodies — missing required fields, wrong types, out-of-domain enum values, or violated numeric constraints — are rejected with `ERR_INVALID_REQUEST` (HTTP 400), and duplicate unique values with `ERR_DUPLICATE` (HTTP 409). Where a segregation-of-duties rule and a state check both apply to the same sign-off or approval, the segregation violation is the higher-priority business-safety guard.

## 3. Business Logic & Workflows

### 3.1. Registering Actors and Storage Units

Before any case can move, the office establishes its people and its cooler inventory, all of which is administrator-only work. An `Admin` registers an investigator by supplying a `full_name` and a unique `badge_no`, optionally marking the record `active` (defaulting to active); an attempt to reuse a `badge_no` already on file is rejected with `ERR_DUPLICATE`. A pathologist is registered with a `full_name` and a unique `license_no`, optionally carrying `is_medical_examiner` (defaulting to false) — this flag is what grants a pathologist the authority to certify. A reused `license_no` likewise yields `ERR_DUPLICATE`.

Cooler units are registered with a unique `label`, a `slot_capacity` of at least one slot, an optional `temperature_c` set-point defaulting to 4 degrees Celsius, and an optional `out_of_service` flag defaulting to false; a duplicate `label` is rejected with `ERR_DUPLICATE`. An administrator may later adjust a cooler's `out_of_service` flag or its `temperature_c` through a simple update that takes no version field; taking a unit out of service blocks all future stores into it. The administrator also owns the logical clock, advancing or rewinding it to a supplied `to_iso8601` instant, which shifts every downstream timestamp and time-gated check.

### 3.2. Reporting a Death and Triage

Anyone may report a death — a member of the public, an investigator, or an administrator — by submitting the decedent's `decedent_name` (the literal value `UNKNOWN` is permitted for John or Jane Doe intakes), the `reported_death_at` instant, the `death_location_county` where the death occurred or the body was found, and the `investigator_user_id` of the lead investigator to be assigned. Reporting creates a case in the `REPORTED` state with its `case_type` initialized to `PENDING`; no authentication is required for this single intake operation.

A case then reaches an investigator's desk for **triage**, which forks the workflow. The investigator supplies the intended `case_type` lane. If the case's `death_location_county` is found in the served-counties configuration, the case advances `REPORTED → ACCEPTED`: its `jurisdiction_status` is set to `ACCEPTED`, `served_county` to true, the requested `case_type` is recorded, and `autopsy_required` is derived from the lane as described in Section 2.8. If instead the county is not among the served counties, triage advances `REPORTED → DECLINED`, a terminal state, setting `jurisdiction_status` to `DECLINED` and `served_county` to false. Triage is legal only from `REPORTED`; attempting it from any other state yields `ERR_INVALID_STATE`. A declined case is a dead end — any subsequent attempt to intake a body, schedule an autopsy, or draft a certificate for it is rejected with `ERR_CASE_DECLINED` (HTTP 409). Each triage increments the case's `version`.

Cases may be retrieved individually with their computed `jurisdiction_status`, `served_county`, `autopsy_required`, and `status` fields, or listed with pagination and optional filtering by `status` or by `investigator_user_id`.

### 3.3. Body Intake, Storage, and Release

Once a case is `ACCEPTED`, the investigation begins in earnest with **body intake**. Intaking a body under a case requires a unique toe-tag `tag_no` (a duplicate tag is rejected with `ERR_DUPLICATE`) and creates a `Body` in the `INTAKE` state associated with its `case_id`. Intaking the first body is the event that advances the case `ACCEPTED → INVESTIGATING`, and both the new body and the parent case's `version` increment as a result. A body's `cooler_unit_id` is null at this point and remains null until the body is stored; likewise `intake_at` is stamped only at storage, `released_at` remains null until release, and the boolean `release_blocked` gates whether the body may ever leave.

Storing a body moves it `INTAKE → STORED`. The request names the destination `cooler_unit_id` and, per the concurrency rule in Section 2.5, the `expected_cooler_version`. The store is permitted only when that cooler is in service — a store into an `out_of_service` unit is rejected with `ERR_COOLER_OUT_OF_SERVICE` (HTTP 409) — and only when it has a free slot, meaning its current `occupied_slots` is strictly less than its `slot_capacity`; a unit whose occupancy has reached capacity is full and rejects the store with `ERR_COOLER_FULL` (HTTP 409). On a successful store the body's `cooler_unit_id` is set, its `storage_status` becomes `STORED`, its `intake_at` is stamped from the logical clock, and `release_blocked` is set to true — a body may not be released until its case reaches certification or an indigent path opens. The chosen cooler's `occupied_slots` is recomputed upward by one and its `version` increments; the body's own `version` increments too.

Releasing a body moves it `STORED → RELEASED`, a terminal state. Release is permitted only while `release_blocked` is false; an attempt to release a still-blocked body is rejected with `ERR_RELEASE_BLOCKED` (HTTP 409). On release the body's `storage_status` becomes `RELEASED`, its `released_at` is stamped from the clock, and its `cooler_unit_id` is cleared to null; the former cooler's `occupied_slots` is recomputed downward by one and that cooler's `version` increments, as does the body's. Bodies may be fetched individually, listed for a case, or listed across the system filtered by `cooler_unit_id`.

### 3.4. Scheduling and Completing an Autopsy

A pathologist schedules an autopsy under a case by supplying the `pathologist_user_id` who will perform it, the requested `scheduled_for` start instant, and a `duration_minutes` of at least 30. Scheduling creates an `AutopsyExam` in `SCHEDULED` tied to its `case_id`, reserves the pathologist's schedule for the requested window, and computes a forward-looking `estimated_fee_cents`. The reserved window is the half-open interval running from `scheduled_for` up to (but not including) `scheduled_for` plus `duration_minutes`. A new exam whose interval overlaps any existing `SCHEDULED` exam for the same `pathologist_user_id` is rejected with `ERR_PATHOLOGIST_DOUBLE_BOOKED` (HTTP 409); two exams that merely touch — one ending exactly when the next begins — are adjacent, not overlapping, and are allowed.

The **estimate** is a quote against the requested plan assuming standard case load. It begins from a base fee of 150,000 cents. The requested duration is billed per whole 30-minute block, with the block count obtained by dividing `duration_minutes` by 30 and rounding up to the next whole block; each block adds 20,000 cents on top of the base. If, and only if, the case's `case_type` is `HOMICIDE`, the sum of base plus duration surcharge is then multiplied by 1.5 and rounded half-up to whole cents. The result is the `estimated_fee_cents`. The estimate carries no overtime and no per-specimen charge.

An autopsy may be completed only once the logical clock has reached or passed its `scheduled_for` instant — an attempt before that time is rejected with `ERR_EXAM_NOT_DUE` (HTTP 409) — and only by the very pathologist recorded on the exam, whose acting identity must equal the exam's `pathologist_user_id`. Completion moves the exam's `exam_status` `SCHEDULED → COMPLETED`, records the `primary_finding` and the proposed `cause_of_death`, computes the `final_fee_cents`, and increments the exam's `version`. Alternatively a scheduled exam may be cancelled, moving it `SCHEDULED → CANCELLED` and releasing the reserved schedule interval so the pathologist's calendar frees up.

The **final fee** is billed at completion against real elapsed time and collected specimens, and it always meets or exceeds the estimate. Elapsed time is the current logical-clock instant minus `scheduled_for`, taken in whole minutes by flooring the second-level difference. The billable minutes are the greater of that elapsed figure and the originally requested `duration_minutes`, so an exam never bills fewer minutes than were scheduled. Those billable minutes are divided by 30 and rounded up to whole blocks, each block again worth 20,000 cents, and added to the 150,000-cent base. A per-specimen add-on is then applied: the system counts the specimens belonging to the case's body whose `chain_status` is either `SENT_TO_LAB` or `CONSUMED` (specimens still `COLLECTED` or already `DISCARDED` are excluded), and adds 5,000 cents for each. Finally, and only for a `HOMICIDE` case, the running subtotal of base plus duration surcharge plus specimen add-on is multiplied by 1.5 and rounded half-up to whole cents — the multiplier is applied strictly after the specimen add-on has been folded in. The result becomes `final_fee_cents`.

### 3.5. Specimens and the Chain of Custody

A pathologist collects a specimen from a body by supplying its `specimen_type` — one of `BLOOD`, `URINE`, `VITREOUS`, or `TISSUE` — creating a `Specimen` in the `COLLECTED` chain state tied to its `body_id`, with `collected_at` stamped from the logical clock. Chain of custody is tracked through `chain_status`. Sending a specimen to the lab moves it `COLLECTED → SENT_TO_LAB`. A collected specimen may instead be discarded, moving it `COLLECTED → DISCARDED`, a terminal state. Each such transition increments the specimen's `version`.

Toxicology begins by ordering a screen against a specimen, supplying the `panel` — one of `BASIC`, `EXPANDED`, or `CONFIRMATORY` — which creates a `ToxScreen` in `ORDERED` tied to its `specimen_id`, with `result_status` initially `ORDERED` and `interpretation` initially `PENDING`. Resulting a screen is a lab technician's action that requires the screen to be `ORDERED` and its parent specimen to be `SENT_TO_LAB`. The technician reports the blood `ethanol_mg_dl` concentration; the screen moves `ORDERED → RESULTED`, and as a cascade the parent specimen's `chain_status` advances `SENT_TO_LAB → CONSUMED` (the assay consumes the specimen), incrementing both the screen's and the specimen's `version`. The `interpretation` is recomputed at this point: it is `POSITIVE` if the reported `ethanol_mg_dl` is at least 80, and `NEGATIVE` otherwise.

A resulted screen may be corrected. Amending a screen overwrites `ethanol_mg_dl` with a new value and recomputes `interpretation` against the same 80-threshold rule, incrementing the screen's `version`. A screen may be amended when it is `RESULTED`, moving it `RESULTED → AMENDED`, and an already-`AMENDED` screen may be amended again, looping `AMENDED → AMENDED` as many times as needed.

### 3.6. Drafting, Signing, and Amending the Death Certificate

The certificate is the case's terminal artifact and the one most tightly guarded. A medical examiner drafts the certificate for a case by supplying the proposed `cause_of_death` text and the asserted `manner_of_death` — one of `NATURAL`, `ACCIDENT`, `HOMICIDE`, or `UNDETERMINED` — creating a `DeathCertificate` in `DRAFT` tied to its `case_id`, with `certifying_me_user_id` null, `signed_at` null, and `amendment_count` at zero. A draft may be discarded outright, moving it `DRAFT → VOID`, a terminal state.

Signing moves the certificate `DRAFT → SIGNED` and is the pivotal compliance gate of the whole system, so it enforces a stack of preconditions. The acting user must be a pathologist whose `is_medical_examiner` flag is true. The segregation-of-duties rule of Section 2.11 applies: the acting examiner's identity must not equal the case's autopsy `pathologist_user_id`, else `ERR_SEGREGATION_VIOLATION`. If the case's `autopsy_required` is true, the case's autopsy exam must be `COMPLETED`, else the sign-off is rejected with `ERR_AUTOPSY_INCOMPLETE` (HTTP 409). The asserted `manner_of_death` must be consistent with the case's `case_type` lane: a `HOMICIDE` case may not be certified with a `NATURAL` manner, a `NATURAL` case may not be certified with a `HOMICIDE` manner, and any inconsistent pairing is rejected with `ERR_MANNER_INCONSISTENT` (HTTP 422); a manner of `UNDETERMINED` is always permitted regardless of lane. Finally, the request must carry `expected_case_version` matching the case's current `version`, or the sign-off fails the optimistic-concurrency check with `ERR_STALE_VERSION` (HTTP 412) as described in Section 2.5.

A successful sign-off sets `cert_status` to `SIGNED`, records the `certifying_me_user_id`, and stamps `signed_at` from the clock. It then cascades: the parent case advances `INVESTIGATING → CERTIFIED`, and because the case is now certified, the case's stored body has its `release_blocked` cleared so the body becomes releasable. The certificate's `version` increments, and the cascaded case mutation increments the case's `version` as well.

After a certificate is signed, a medical examiner may amend it — for instance, when a late toxicology result changes the finding. Amending overwrites the `cause_of_death` and `manner_of_death`, increments the `amendment_count`, and increments the certificate's `version`; the case itself remains `CERTIFIED`. An amendment requires the acting user to be a medical examiner (`is_medical_examiner` true). The first amendment moves the certificate `SIGNED → AMENDED`, and a certificate already in `AMENDED` may be amended again, looping `AMENDED → AMENDED`. Certificates may be fetched individually, listed for a case (zero or one), or listed across the system filtered by `certifying_me_user_id`.

### 3.7. Next of Kin and Property Release

Alongside the forensic workflow runs the custody of the decedent's personal effects. An investigator records a next-of-kin for a case by supplying a `full_name` and the `relationship` — one of `SPOUSE`, `CHILD`, `PARENT`, `SIBLING`, or `OTHER` — creating a `NextOfKin` tied to its `case_id`, initially with `verified` false and `contacted_at` stamped from the clock (the earliest contact instant serves as a kin-priority tie-break). An investigator later verifies a kin's identity, flipping `verified` to true and incrementing that record's `version`; verification is the gate that later permits a property release to be approved.

An investigator inventories the decedent's personal effects as property items, each carrying a free-text `description` and an appraised `valuation_cents` of zero or more, created in the `HELD` state and tied to its `case_id`. To hand those effects to a family member, an investigator requests a release by naming the receiving `next_of_kin_id`, creating a `PropertyRelease` in `REQUESTED` tied to its `case_id`.

Approving a release moves it `REQUESTED → APPROVED` and is guarded. The referenced next-of-kin must have `verified` true, or the approval is rejected with `ERR_KIN_UNVERIFIED` (HTTP 409). The case must already be `CERTIFIED` or `CLOSED`. And the segregation-of-duties rule applies: the acting investigator's identity must not equal the case's lead `investigator_user_id`, else `ERR_SEGREGATION_VIOLATION`. On approval the release records the `approver_user_id`, sets `release_status` to `APPROVED`, and cascades — every property item for the case still in `HELD` is flipped to `RELEASED`, and the count of items so flipped is recorded on the release as `released_item_count`; the release's `version` increments. Alternatively a requested release may be denied, moving it `REQUESTED → DENIED`. Releases may be fetched individually or listed for a case or across the system, filtered by `next_of_kin_id` or by `approver_user_id`.

### 3.8. Indigent Disposition and Case Closure

When a decedent has no claiming family, the county assumes responsibility for burial. An investigator declares an indigent disposition for a case by supplying the county's `statutory_allowance_cents` ceiling and the `itemized_cost_cents` of the submitted burial costs (each zero or more), creating an `IndigentDisposition` in `DECLARED` tied to its `case_id`.

A medical examiner approves the disposition, moving its `disposition_status` `DECLARED → APPROVED`, but only when the case has no claiming kin — that is, no next-of-kin for the case has `verified` true; if any verified kin exists the approval is rejected with `ERR_KIN_CLAIMANT_EXISTS` (HTTP 409). Approval computes the `county_payable_cents` the county owes, through a pinned three-step waterfall. First, the decedent's estate offsets the cost: the estate value is the sum of `valuation_cents` across the case's property items still in `HELD`. Second, the cost owed after the estate is applied is the `itemized_cost_cents` minus that estate value, floored at zero so it never goes negative. Third, the county pays the smaller of that post-estate cost and the `statutory_allowance_cents` ceiling. Because the estate is applied before the cap, a case with substantial held property can drive the county's share below the itemized cost even when the itemized cost was already under the allowance. Approval also cascades to clear the body's `release_blocked` so the body may be released for burial, and increments the disposition's `version`.

Recording the burial moves the disposition `APPROVED → BURIED` and is permitted only once the case's body has reached `RELEASED`. Burial cascades a final settlement of the estate: every property item for the case still in `HELD` is escheated to the state, flipping its `item_status` to `ESCHEATED`, and the disposition's `version` increments. A property item thus lives its life across the `HELD`, `RELEASED`, and `ESCHEATED` states depending on whether it is released to family or escheated at an indigent burial.

Finally, an investigator closes a certified case, moving it `CERTIFIED → CLOSED`, a terminal state. Closure is permitted only when the case's body has been `RELEASED` and no property item for the case remains in `HELD`. On closure the case's `closed_at` is stamped from the clock and its `version` increments.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions, verifications, and clock manipulation — return `200 OK`. The request body, computed side effects, and cascades for each operation are specified in the Section 3 narratives; the table below lists only the transport contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/investigators` | Register an investigator | Admin |
| GET | `/investigators/{id}` | Fetch an investigator | Admin, Investigator, MedicalExaminer |
| POST | `/pathologists` | Register a pathologist | Admin |
| GET | `/pathologists/{id}` | Fetch a pathologist | Admin, Pathologist, MedicalExaminer, Investigator |
| POST | `/cooler-units` | Register a cooler/morgue storage unit | Admin |
| GET | `/cooler-units/{id}` | Fetch a cooler unit with current occupancy | Admin, Investigator |
| PATCH | `/cooler-units/{id}` | Update cooler out-of-service or temperature | Admin |
| GET | `/cooler-units/{id}/occupancy-report` | Computed occupancy report (body-days and occupied slots) | Admin, Investigator |
| POST | `/cases` | Report a death (intake) | Anonymous, Investigator, Admin |
| GET | `/cases/{id}` | Fetch a case | Admin, Investigator, MedicalExaminer, Pathologist |
| GET | `/cases` | List cases (filter by status or investigator) | Admin, Investigator, MedicalExaminer |
| POST | `/cases/{id}/triage` | Triage jurisdiction and assign case-type lane | Investigator |
| POST | `/cases/{id}/close` | Close a certified case | Investigator |
| POST | `/cases/{id}/bodies` | Intake a body under a case | Investigator |
| GET | `/cases/{id}/bodies` | List bodies for a case | Admin, Investigator, MedicalExaminer |
| GET | `/bodies/{id}` | Fetch a body | Admin, Investigator, MedicalExaminer |
| GET | `/bodies` | List bodies (filter by cooler) | Admin, Investigator |
| POST | `/bodies/{id}/store` | Store a body into a cooler slot | Investigator |
| POST | `/bodies/{id}/release` | Release a body from a cooler | Investigator |
| POST | `/cases/{id}/autopsy-exams` | Schedule an autopsy for a case | Pathologist |
| GET | `/cases/{id}/autopsy-exams` | List autopsy exams for a case | Admin, Investigator, MedicalExaminer, Pathologist |
| GET | `/autopsy-exams/{id}` | Fetch an autopsy exam | Admin, Investigator, MedicalExaminer, Pathologist |
| GET | `/autopsy-exams` | List autopsy exams (filter by pathologist) | Admin, Pathologist, MedicalExaminer |
| POST | `/autopsy-exams/{id}/complete` | Complete an autopsy | Pathologist |
| POST | `/autopsy-exams/{id}/cancel` | Cancel a scheduled autopsy | Pathologist |
| POST | `/bodies/{id}/specimens` | Collect a specimen from a body | Pathologist |
| GET | `/bodies/{id}/specimens` | List specimens for a body | Admin, Pathologist, MedicalExaminer, Investigator |
| GET | `/specimens/{id}` | Fetch a specimen | Admin, Pathologist, MedicalExaminer, LabTech |
| POST | `/specimens/{id}/send-to-lab` | Send a specimen to the lab | Pathologist |
| POST | `/specimens/{id}/discard` | Discard a specimen | Pathologist |
| POST | `/specimens/{id}/tox-screens` | Order a toxicology screen | Pathologist, LabTech |
| GET | `/specimens/{id}/tox-screens` | List tox screens for a specimen | Admin, Pathologist, MedicalExaminer, LabTech |
| GET | `/tox-screens/{id}` | Fetch a tox screen | Admin, Pathologist, MedicalExaminer, LabTech |
| POST | `/tox-screens/{id}/result` | Report a toxicology result | LabTech |
| POST | `/tox-screens/{id}/amend` | Amend a resulted tox screen | LabTech |
| POST | `/cases/{id}/death-certificate` | Draft the death certificate | MedicalExaminer |
| GET | `/cases/{id}/death-certificate` | List the case's death certificate (0 or 1) | Admin, Investigator, MedicalExaminer |
| GET | `/death-certificates/{id}` | Fetch a death certificate | Admin, Investigator, MedicalExaminer |
| GET | `/death-certificates` | List death certificates (filter by certifying ME) | Admin, Investigator, MedicalExaminer |
| POST | `/death-certificates/{id}/sign` | Sign a death certificate | MedicalExaminer |
| POST | `/death-certificates/{id}/amend` | Amend a signed certificate | MedicalExaminer |
| POST | `/death-certificates/{id}/void` | Void a draft certificate | MedicalExaminer |
| POST | `/cases/{id}/next-of-kin` | Record a next-of-kin for a case | Investigator |
| GET | `/cases/{id}/next-of-kin` | List next-of-kin for a case | Admin, Investigator, MedicalExaminer |
| GET | `/next-of-kin/{id}` | Fetch a next-of-kin | Admin, Investigator, MedicalExaminer |
| POST | `/next-of-kin/{id}/verify` | Verify a next-of-kin's identity | Investigator |
| POST | `/cases/{id}/property-items` | Add a personal-effects inventory item | Investigator |
| GET | `/cases/{id}/property-items` | List property items for a case | Admin, Investigator, MedicalExaminer |
| GET | `/property-items/{id}` | Fetch a property item | Admin, Investigator, MedicalExaminer |
| POST | `/cases/{id}/property-releases` | Request release of held property to a kin | Investigator |
| GET | `/cases/{id}/property-releases` | List property releases for a case | Admin, Investigator, MedicalExaminer |
| GET | `/property-releases/{id}` | Fetch a property release | Admin, Investigator, MedicalExaminer |
| GET | `/property-releases` | List property releases (filter by kin or approver) | Admin, Investigator, MedicalExaminer |
| POST | `/property-releases/{id}/approve` | Approve a property release | Investigator |
| POST | `/property-releases/{id}/deny` | Deny a property release | Investigator |
| POST | `/cases/{id}/indigent-disposition` | Declare an indigent disposition | Investigator |
| GET | `/cases/{id}/indigent-disposition` | List the case's indigent disposition (0 or 1) | Admin, Investigator, MedicalExaminer |
| GET | `/indigent-dispositions/{id}` | Fetch an indigent disposition | Admin, Investigator, MedicalExaminer |
| POST | `/indigent-dispositions/{id}/approve` | Approve an indigent disposition | MedicalExaminer |
| POST | `/indigent-dispositions/{id}/bury` | Record burial | Investigator |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_DECLINED` | 409 Conflict |
| `ERR_MANNER_INCONSISTENT` | 422 Unprocessable Entity |
| `ERR_AUTOPSY_INCOMPLETE` | 409 Conflict |
| `ERR_EXAM_NOT_DUE` | 409 Conflict |
| `ERR_COOLER_FULL` | 409 Conflict |
| `ERR_COOLER_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_PATHOLOGIST_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_RELEASE_BLOCKED` | 409 Conflict |
| `ERR_KIN_UNVERIFIED` | 409 Conflict |
| `ERR_KIN_CLAIMANT_EXISTS` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
