# Building Envelope Consulting API — Product Requirements Document

## 1. Introduction

Building enclosure failures — uncontrolled water ingress, excessive air leakage, thermal bridging, trapped moisture — are among the most expensive defect categories in modern construction, and the consulting practice that diagnoses and remediates them runs an unusually dense workflow. Design details must be reviewed before construction begins; laboratory mock-ups must be built and performance-tested in rented chamber time; installed assemblies must be field-tested and their failures diagnosed; thermal and moisture conditions must be surveyed; remediation must be specified, costed, and superseded as conditions change; warranty recovery must be pursued against manufacturers; evidence must be sealed when disputes escalate to litigation; and long-running maintenance programs must be scheduled without collisions. This document specifies the Building Envelope Consulting & Testing API, the system of record that coordinates that entire practice for a single consulting firm.

The API is organized around the **Engagement**, a client commission that carries a hard fee cap, a standard labor rate, a live risk score, and a derived operating posture that gates what work may proceed at any moment. Around the Engagement sit the artifacts of the practice: assemblies, design review rounds, chamber bookings, mock-ups, field tests, surveys, anomalies, remediation plans, warranty claims, litigation holds, maintenance visits, and invoices. Three concerns are enforced system-wide rather than left to convention: segregation of duties between the people who perform work and the people who certify or approve it; disciplined fee recognition, in which every fee-bearing event is provisionally accrued the moment it occurs and definitively recomputed at close-out; and a posture mechanism that automatically restricts or freezes an engagement when risk deteriorates, when critical anomalies are verified, or when a litigation hold is applied.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contractual formats, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400).

The system recognizes exactly five roles, spelled precisely as follows: `Principal`, `Consultant`, `Reviewer`, `FieldTechnician`, and `ManufacturerRep`. The `Principal` is the principal-in-charge who owns the engagement lifecycle, litigation holds, field-test certification, and payment events. The `Consultant` is the building-envelope consultant who registers assemblies, submits design reviews and revisions, manages mock-ups and chamber bookings, schedules field tests and surveys, runs diagnosis, raises and verifies anomalies, drafts and issues remediation plans, files and resolves warranty claims, schedules maintenance, and drafts invoices. The `Reviewer` is the independent design reviewer who starts review rounds, issues comments, and approves or rejects them. The `FieldTechnician` performs field tests, records their results, completes surveys, and completes maintenance visits. The `ManufacturerRep` acknowledges and decides warranty claims on behalf of a manufacturer. An attempt to perform an operation outside the caller's role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

For every one of these five roles — `Principal`, `Consultant`, `Reviewer`, `FieldTechnician`, and `ManufacturerRep` — the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it on resources where a transition writes it (for example, as `performed_by` or `certified_by` on a field test, or as `reviewer_id` on a design review round), but it never compares `X-User-ID` against any entity's `id` for ownership purposes. Access control is purely role-based.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside the 1-to-100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order; resources created at the same timestamp are ordered by creation sequence, earliest-created first.

Paginated list responses include the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope; `has_more` is true exactly when further items remain beyond the returned page — that is, when `offset` plus the number of items returned is less than `total_count`.

### 2.4. The Logical Clock

The server evaluates every date- and time-dependent rule against a **logical clock**, never against wall-clock time. At server startup, before any clock-setting call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`; the server never falls back to wall-clock time if the clock has not been explicitly set.

A `Principal`-only test-driving capability advances the logical clock. The request carries a single field, `to_iso8601`, an ISO 8601 UTC instant, and the response reports the new reading as `current_utc`. Setting the clock mutates no entity; it only changes the instant against which temporal rules are judged.

Three families of rules read the logical clock: the half-open chamber-slot occupancy windows that gate mock-up testing, the closed maintenance-visit windows that gate visit completion, and the thirty-day manufacturer response window that gates warranty-claim escalation. Each is described with its workflow in §3.

### 2.5. Engagement Lifecycle, Derived Posture, and Operational Gating

Every Engagement moves through a linear lifecycle: `SETUP` at creation, then `IN_PROGRESS` after activation, then `CLOSE_OUT` when final accounting begins, and finally the terminal `CLOSED` state. As a general rule, every operation that creates or mutates a child resource of an engagement requires the engagement to be `IN_PROGRESS`; such an operation attempted under any other lifecycle stage is rejected with `ERR_ENGAGEMENT_NOT_IN_PROGRESS` (HTTP 409). The engagement's own lifecycle transitions are the exception, since each of them explicitly targets a different stage.

Distinct from that lifecycle `status`, each engagement carries a derived `posture` — one of `OPEN`, `RESTRICTED`, or `FROZEN` — which the server recomputes after every event that touches its inputs: every risk-score change, every anomaly status change, every litigation-hold application or release, and every fee-affecting transition. The derivation is evaluated in a fixed order. If the engagement's `litigation_hold_active` flag is true, the posture is `FROZEN`. Otherwise, if the engagement's `risk_score` is below 40, or if any anomaly of the engagement is simultaneously in `VERIFIED` status and of `CRITICAL` severity, the posture is `FROZEN`. Otherwise, if the `risk_score` is below 70, or if any anomaly of the engagement is in `OPEN` status, the posture is `RESTRICTED`. Only when none of those conditions holds is the posture `OPEN`. Note the asymmetry deliberately encoded here: an `OPEN` anomaly restricts but does not freeze; only a verified critical anomaly, a low risk score, or a litigation hold freezes.

A `FROZEN` posture blocks seven operational mutations, each rejected with `ERR_ENGAGEMENT_FROZEN` (HTTP 409): starting a design review round, beginning mock-up construction, beginning a field test, certifying a field test, completing a survey, completing a remediation plan, and issuing an invoice. Two further operations demand the stronger condition that the posture be exactly `OPEN`: approving a design review round and issuing a remediation plan. Under either `RESTRICTED` or `FROZEN`, those two operations are rejected with `ERR_POSTURE_NOT_OPEN` (HTTP 409). A `RESTRICTED` posture blocks only those two operations; every other workflow proceeds normally.

### 2.6. The Engagement Risk Score

Each engagement carries a read-only integer `risk_score` that begins at 100 when the engagement is created. Lower is worse. The score is bounded below by a floor of 0 and above by a ceiling of 100, and the bound is applied after every single delta — the clamping happens per event, which matters when several anomalies are remediated in one cascade, because each recovery is clamped individually before the next is applied.

Four kinds of events move the score. A mock-up test failure subtracts 25. A field test whose computed result is a failure subtracts 25. Verifying an anomaly subtracts an amount keyed to the anomaly's severity: 15 for `CRITICAL`, 10 for `HIGH`, 5 for `MEDIUM`, and 2 for `LOW`. Each anomaly that reaches `REMEDIATED` through completion of a covering remediation plan adds 10 back, subject to the ceiling. Every one of these movements triggers a fresh posture derivation as described in §2.5, so a single failure can flip an engagement from `OPEN` to `RESTRICTED` or `FROZEN` in the same request that records it.

### 2.7. Fee Recognition, Headroom, and the Fee Cap

An engagement is created with two fiscal inputs: `fee_cap_cents`, a hard cap on recognized fees that must be an integer of at least 1, and `labor_rate_cents_per_hour`, the standard hourly labor rate used by invoice calculations, likewise an integer of at least 1. Against those inputs the server maintains three read-only figures on the engagement. `recognized_fees_cents` is the cumulative recognized fee total on the provisional accrual basis; it starts at 0 and moves incrementally as fee-bearing events occur. `invoiced_cents` is the sum of `total_cents` over the engagement's invoices whose status is `ISSUED` or `PAID`, recomputed whenever an invoice enters or leaves that set. `fee_headroom_cents` is exactly the engagement's `fee_cap_cents` minus its `recognized_fees_cents`.

Fee recognition operates in two variants. The **provisional** variant is a running accumulator: each fee event — a design review round reaching `APPROVED` or `REJECTED`, a mock-up test reaching `PASSED` or `FAILED`, a remediation plan being issued, completed, or superseded, or a warranty claim being resolved — applies its signed delta to `recognized_fees_cents` at transition time, and the accumulator is floored at 0 after each step so the provisional total can never go negative. The **final** variant runs once, at the moment the engagement moves from `IN_PROGRESS` to `CLOSE_OUT`: the server recomputes recognized fees from scratch by replaying every fee-bearing event of the engagement in chronological order (ordered by event timestamp ascending, ties broken by event creation timestamp ascending), summing only the positive fee events. Warranty-recovery offsets are excluded from the final replay entirely — the final accrual treats recoveries as contra-revenue reported separately rather than netted against fees — and no intermediate floor is applied. The two variants therefore legitimately diverge whenever a warranty claim has resolved before close-out.

The provisional variant is guarded by a fiscal gate: any transition that would provisionally recognize fees is rejected with `ERR_FEE_CAP_EXCEEDED` (HTTP 402) when applying the event would push `fee_headroom_cents` below zero. Issuing an invoice applies a stricter comparison of the same family: the engagement's `fee_headroom_cents` must be at least the invoice's full `total_cents`, or issuance is rejected with `ERR_FEE_CAP_EXCEEDED`. Only the final accrual at close-out is exempt from the gate — `fee_headroom_cents` is permitted to go negative exclusively through that recomputation.

### 2.8. Monetary Precision and Rounding

All monetary values in the system are integer cents. Where a calculation produces a fractional cent at a pinned rounding step, the value is rounded half-up to whole cents at that step — never earlier, never later. Four calculations carry such a pinned step: the revision surcharge of the design review fee (rounded half-up before being added to the base and barrier surcharge), the per-day chamber charge of the mock-up testing fee (rounded half-up per day before any multiplication by day count or attempt number), the contingency product of a remediation plan's estimated cost (rounded half-up after the multiplier is applied), and both the labor multiplication and the final total of the invoice calculation (each rounded half-up at its own step). Leakage comparisons, by contrast, are performed in exact decimal arithmetic with no rounding applied to either side.

### 2.9. Optimistic Concurrency Control on the Engagement

Exactly two write operations are guarded by optimistic concurrency control against the parent Engagement's `version`: creating a remediation plan (`POST /engagements/{id}/remediation-plans`) and issuing a remediation plan (`POST /engagements/{id}/remediation-plans/{planId}/issue`). Each of these requests must carry the field `expected_engagement_version`, holding the engagement `version` the client last observed; the field is not optional on these two operations. If the supplied value does not equal the engagement's current `version` — meaning another write has advanced the engagement since the client last read it — the request is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412), and no change is applied. This protects the remediation ledger specifically: both operations mutate recognized fees, and plan creation can additionally supersede a previously issued plan, so a client acting on an unobserved engagement state would otherwise reverse or duplicate recognition it has never seen. No endpoint outside these two accepts a version field. On the Engagement specifically, `version` increments only where a transition says so explicitly — activation (§3.1), remediation-plan creation and issuance (§3.7), litigation-hold application and release (§3.9), and the two closing transitions (§3.9); risk-score movements, provisional fee accruals, posture re-derivations, remediation-plan completion, and invoice status changes refresh the engagement's `updated_at` without incrementing its `version`.

### 2.10. Common Resource Properties and Nested Retrieval

Nearly every resource in the API carries a standard set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, updated on every mutation of the resource.
- `version` (integer): a system-managed integer that increments with every modification of the resource; an Engagement begins at version 1 when created.

Two resource types deliberately carry a reduced property set: a **LitigationHold** and an **Invoice** each expose only `id` and `created_at`. Neither has `updated_at` nor `version` — a released hold and a finalized invoice are immutable audit records, and the absence of the mutation-tracking fields reflects that.

Requests that target nested resources are validated strictly left to right along the path. The server first confirms the existence of the engagement named by the path, then the existence of the child resource within that engagement, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve. Existence of the container is therefore always settled before any business rule about the child is consulted. The same `ERR_NOT_FOUND` rejection applies to resource identifiers carried in the request body rather than the path — `assembly_id` on design-review, mock-up, field-test, and survey creation, `chamber_slot_id` on mock-up creation, the parent reference on anomaly creation, `anomaly_id` on warranty-claim filing, and every entry of a remediation plan's `anomaly_ids`: each is resolved against the engagement named in the path after the lifecycle gate, and a reference that does not resolve to a resource of that engagement is rejected with `ERR_NOT_FOUND` (HTTP 404). Beyond the nested routes, the API also offers flat lookup routes that fetch a single assembly, chamber slot, field test, survey, anomaly, or remediation plan directly by its `id`, plus flat listing routes that expose the children of a given assembly, chamber slot, field test, survey, or anomaly; §4 enumerates them.

### 2.11. Validation Order

When a request violates more than one rule, the error it receives is determined by a fixed evaluation order rather than by whichever check happens to run first. The order, from earliest to latest, is:

1. Presence and non-emptiness of the authentication headers `X-User-ID` and `X-User-Role` — otherwise `ERR_MISSING_USER_CONTEXT`.
2. Role permission for the invoked endpoint — otherwise `ERR_FORBIDDEN_ROLE`.
3. Existence of every resource named in the path, validated left to right from the engagement down to the child — otherwise `ERR_NOT_FOUND`.
4. Request-body shape: the body itself a valid JSON object, required fields present, calendar-date fields strictly in `YYYY-MM-DD` form, enum fields within their declared sets, numeric ranges respected (the fee cap at least 1, a slot's end date strictly later than its start date, a visit's window end not earlier than its window start, and so on), and the anomaly parentage rule that exactly one of its two parent references is set — otherwise `ERR_INVALID_REQUEST`.
5. The engagement lifecycle gate: child creation and transition operations require the engagement to be `IN_PROGRESS` — otherwise `ERR_ENGAGEMENT_NOT_IN_PROGRESS`.
6. The posture gates: a `FROZEN` posture blocks the operational mutations enumerated in §2.5 with `ERR_ENGAGEMENT_FROZEN`, and the two operations that require an exactly `OPEN` posture fail with `ERR_POSTURE_NOT_OPEN`.
7. The target entity's own state preconditions for the invoked transition — the family of not-actionable errors such as `ERR_REVIEW_NOT_ACTIONABLE`, `ERR_MOCKUP_NOT_ACTIONABLE`, `ERR_FIELD_TEST_NOT_ACTIONABLE`, `ERR_SURVEY_NOT_ACTIONABLE`, `ERR_ANOMALY_NOT_OPEN`, `ERR_PLAN_NOT_ACTIONABLE`, `ERR_CLAIM_NOT_ACTIONABLE`, `ERR_VISIT_NOT_SCHEDULED`, `ERR_INVOICE_NOT_DRAFT`, `ERR_INVOICE_NOT_ISSUED`, `ERR_HOLD_NOT_ACTIVE`, and `ERR_SLOT_NOT_RESERVED`, chosen per target entity.
8. Segregation of duties — `ERR_DUTY_SEGREGATION_VIOLATION`.
9. Temporal window conditions — `ERR_OUTSIDE_SLOT_WINDOW`, `ERR_OUTSIDE_VISIT_WINDOW`, `ERR_ESCALATION_WINDOW_NOT_ELAPSED`, and `ERR_IMAGING_DELTA_T_INSUFFICIENT`.
10. Creation-time business constraints, which share a single priority tier: chamber-slot and maintenance-visit window overlap (`ERR_WINDOW_OVERLAP`), assembly tag uniqueness (`ERR_DUPLICATE_ASSEMBLY_TAG`), and the supersede-target rule for remediation plans (`ERR_SUPERSEDES_NOT_ISSUED`).
11. Referential preconditions — `ERR_ASSEMBLY_NOT_APPROVED`, `ERR_ANOMALY_NOT_VERIFIED`, and `ERR_DIAGNOSIS_INCOMPLETE`.
12. The fiscal gate — `ERR_FEE_CAP_EXCEEDED`.
13. The optimistic-concurrency check on the two remediation-plan writes — `ERR_STALE_ENGAGEMENT_VERSION`.

This ordering has observable consequences. A design-review approval attempted by the same reviewer who issued the round's comments, on an engagement whose posture is `RESTRICTED`, surfaces `ERR_POSTURE_NOT_OPEN` from tier 6 rather than the segregation violation from tier 8. A remediation-plan issuance that would breach the fee cap while carrying a stale engagement version surfaces `ERR_FEE_CAP_EXCEEDED` from tier 12, not `ERR_STALE_ENGAGEMENT_VERSION` from tier 13.

## 3. Business Logic & Workflows

### 3.1. Opening an Engagement and Registering Assemblies

A `Principal` opens a new commission by creating an Engagement with a `name`, the `client_name` of the commissioning organization, the `fee_cap_cents` hard cap, and the `labor_rate_cents_per_hour` billing rate. The new engagement starts in `SETUP` with `risk_score` at 100, `posture` derived as `OPEN`, `recognized_fees_cents` and `invoiced_cents` at 0, `litigation_hold_active` false, and `version` 1. Activation by a `Principal` moves the engagement from `SETUP` to `IN_PROGRESS`; attempting activation from any other state is rejected with `ERR_ENGAGEMENT_NOT_IN_SETUP` (HTTP 409). Activation recomputes the derived posture and increments the engagement's `version` by 1. Only once the engagement is `IN_PROGRESS` may child work of any kind be created or mutated, per the lifecycle gate of §2.5.

With the engagement live, a `Consultant` registers the **assemblies** under scope — the curtain-wall panels, window-wall runs, masonry elevations, roofing sections, and plaza decks that the practice will review and test. Each assembly is created with a `tag` (a short label such as W1-NORTH), an `assembly_type` drawn from exactly `CURTAIN_WALL`, `WINDOW_WALL`, `MASONRY`, `ROOFING`, or `PLAZA_DECK`, a `design_u_factor` expressing the design thermal transmittance in watts per square metre-kelvin (a number greater than 0 and at most 6.0), and a `required_airtightness_lps_m2` expressing the specified air-leakage limit at the 75-pascal reference pressure, in litres per second per square metre (a number greater than 0 and at most 3.0). The `tag` must be unique within the engagement under case-sensitive comparison; a duplicate registration is rejected with `ERR_DUPLICATE_ASSEMBLY_TAG` (HTTP 409). Every assembly records its owning engagement in `engagement_id`, and its `review_status` begins at `NONE`, reflecting that no design review round has yet been started against it.

### 3.2. The Design Review Cycle

Design review is a cyclic conversation between the `Consultant` who submits drawing packages and the independent `Reviewer` who judges them. A `Consultant` opens a round by submitting a design review against an assembly: the payload names the `assembly_id`, declares the `barrier_scope` as a non-empty list with no duplicates drawn from the barrier layers `AIR`, `WATER`, and `THERMAL`, and states the `drawing_count` of detail sheets under review, an integer of at least 1. The new review round starts in `SUBMITTED` with `revision_round` at 0 and `reviewer_id` unset; it is linked to the engagement through its own `engagement_id`.

A `Reviewer` picks the round up, moving it from `SUBMITTED` to `UNDER_REVIEW`. This first pick-up requires the engagement to be `IN_PROGRESS` and its posture to be other than `FROZEN`; violations surface as `ERR_ENGAGEMENT_NOT_IN_PROGRESS` or `ERR_ENGAGEMENT_FROZEN`, and starting a round that is not in `SUBMITTED` (or, on the re-entry path described below, not in `REVISED`) is rejected with `ERR_REVIEW_NOT_ACTIONABLE` (HTTP 409). The moment a round enters `UNDER_REVIEW`, the reviewed assembly's `review_status` moves to `IN_REVIEW`. When the `Reviewer` has finished reading, issuing comments moves the round from `UNDER_REVIEW` to `COMMENTS_ISSUED` and records the issuing reviewer's `X-User-ID` in the round's `reviewer_id`. A `Consultant` then answers with a revision, moving the round from `COMMENTS_ISSUED` to `REVISED` and incrementing `revision_round` by 1. A `Reviewer` may start the next look, which cycles the round from `REVISED` back to `UNDER_REVIEW`; the `reviewer_id` recorded on the prior round is deliberately retained through this re-entry, because it anchors the segregation-of-duties check at approval time.

Two terminal outcomes exist. Approval by a `Reviewer` moves the round from `UNDER_REVIEW` to `APPROVED` and is guarded by three conditions: the round must be `UNDER_REVIEW`; if the round has been revised at least once (that is, `revision_round` is 1 or more), the approving reviewer's `X-User-ID` must differ from the `reviewer_id` who issued the current round's comments — the reviewer who issued comments on a round may never approve that same round, and a violation is rejected with `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 403); and the engagement's posture must be exactly `OPEN`, else `ERR_POSTURE_NOT_OPEN`. Approval flips the assembly's `review_status` to `APPROVED`, computes the round's `review_fee_cents` as described below, adds that fee to the engagement's `recognized_fees_cents` under the provisional accrual of §2.7, and re-derives the engagement posture. Rejection by a `Reviewer` moves the round from `UNDER_REVIEW` to `REJECTED` with no condition beyond the round's state; it flips the assembly's `review_status` to `REJECTED` and — because rejected rounds still bill — computes the same `review_fee_cents` by the same formula, adds it to `recognized_fees_cents`, and re-derives posture.

The design review fee is a tiered price evaluated in a pinned order: base tier first, then barrier surcharge, then revision surcharge, all in integer cents. The base depends on `drawing_count`: a round reviewing at most 5 drawings bills a flat 250000 cents; a round reviewing more than 5 but at most 15 drawings bills 250000 cents plus 30000 cents for each drawing beyond the fifth; a round reviewing more than 15 drawings bills 250000 cents plus 300000 cents (the full second tier) plus 20000 cents for each drawing beyond the fifteenth. The barrier surcharge adds 40000 cents for each barrier layer in `barrier_scope` beyond the first. The revision surcharge is ten percent of the base for each completed revision round — `revision_round` multiplied by ten percent of the base — rounded half-up to whole cents. The fee is the sum of the base, the barrier surcharge, and the rounded revision surcharge.

The engagement's review list can be filtered by `assembly_id` to follow a single assembly's review history. Each round's record exposes `status`, `revision_round`, `reviewer_id`, and `review_fee_cents` alongside its inputs — `review_fee_cents` remaining null until the round reaches `APPROVED` or `REJECTED` — so the full negotiation trail remains auditable.

### 3.3. Laboratory Mock-Ups and Chamber Time

Performance mock-ups are tested against rented laboratory chamber windows, so the practice books chamber time before specimens are built. A `Consultant` reserves a chamber slot by naming the `chamber_code` of the laboratory chamber, a `start_date`, an `end_date`, and a `daily_rate_cents` of at least 1. The occupancy window is half-open: the slot covers `start_date` itself and every day up to but not including `end_date`, so `end_date` must be a strictly later day than `start_date`. A new reservation is rejected with `ERR_WINDOW_OVERLAP` (HTTP 409) when its half-open window would intersect the half-open window of any existing `RESERVED` or `CONSUMED` slot booked under the same `chamber_code` on the same engagement; two windows that merely touch at a boundary day — one ending on the day the other begins — do not conflict. A slot is created in `RESERVED`.

A reserved slot can be handed back: releasing it moves it from `RESERVED` to `RELEASED`. Release is refused with `ERR_SLOT_NOT_RESERVED` when the slot is not currently `RESERVED`, and with `ERR_SLOT_IN_USE` (HTTP 409) when any mock-up in `PLANNED`, `CONSTRUCTING`, `READY_FOR_TEST`, or `REMEDIATED` still references it. The only other exit from `RESERVED` is automatic: the slot flips to `CONSUMED` the moment a mock-up enters `TESTING` against it.

A `Consultant` creates a mock-up bound to an assembly and to the chamber slot that will host its first testing entry, providing `assembly_id`, `chamber_slot_id`, and the `specimen_count` of test specimens in the rig, an integer of at least 1. The mock-up is created in `PLANNED` with `attempt_number` 1 and both `air_leakage_lps_m2` and `testing_fee_cents` unset. Beginning construction moves it from `PLANNED` to `CONSTRUCTING` and is blocked under a `FROZEN` posture with `ERR_ENGAGEMENT_FROZEN`; declaring it built moves it from `CONSTRUCTING` to `READY_FOR_TEST`. Beginning the test moves it from `READY_FOR_TEST` to `TESTING`, and this step enforces two conditions beyond state: the bound chamber slot must still be `RESERVED` — otherwise `ERR_SLOT_NOT_RESERVED` — and the logical clock's current date must fall inside that slot's half-open window, on `start_date` or any later day before `end_date`, otherwise `ERR_OUTSIDE_SLOT_WINDOW` (HTTP 409). A successful start consumes the slot. Any of these mock-up transitions invoked against a mock-up in the wrong state is rejected with `ERR_MOCKUP_NOT_ACTIONABLE` (HTTP 409).

Recording the outcome is a server-branched transition driven by a single payload field, `measured_leakage_lps_m2`. The measured value is compared against the tested assembly's `required_airtightness_lps_m2`: a measurement at most equal to the requirement — equality included — passes, and the mock-up moves from `TESTING` to `PASSED`; a measurement strictly greater than the requirement fails, and the mock-up moves from `TESTING` to `FAILED`. Either way, the measurement is stored in `air_leakage_lps_m2`, the laboratory fee is computed into `testing_fee_cents`, and that fee is added to the engagement's `recognized_fees_cents`. A `FAILED` outcome additionally subtracts 25 from the engagement's `risk_score` (clamped at the floor of 0), and both outcomes re-derive the engagement posture.

The mock-up testing fee multiplies a per-day charge by the length of the consumed slot and by the attempt count, with rounding pinned per day. The slot length in days is the whole-day count of its half-open window — the number of days from `start_date` up to but not including `end_date`. The per-day charge is the slot's `daily_rate_cents` increased by a specimen surcharge of five percent for each specimen beyond the first; that per-day figure is rounded half-up to whole cents first, and only then multiplied by the day count and by the mock-up's `attempt_number`. Rounding once at the end instead is a different, explicitly rejected variant.

A failed rig is not the end of the road. Marking it remediated moves the mock-up from `FAILED` to `REMEDIATED`. A remediated mock-up re-enters `TESTING` through the same begin-testing action, but from `REMEDIATED` the request must carry `new_chamber_slot_id`, referencing a chamber slot of the same engagement that is currently `RESERVED` — a missing or non-reserved reference is rejected with `ERR_SLOT_NOT_RESERVED` — and the logical clock's date must fall inside that new slot's half-open window, otherwise `ERR_OUTSIDE_SLOT_WINDOW`. On re-entry the mock-up's `attempt_number` increments by 1, its `chamber_slot_id` is re-pointed to the new slot, and the new slot flips to `CONSUMED`; the previously consumed slot stays `CONSUMED`. Because the fee formula multiplies by `attempt_number`, each retest bills proportionally more chamber time. Mock-up lists can be filtered by `assembly_id`, and the set of mock-ups bound to a chamber slot can be read back through the flat listing route for that slot.

### 3.4. Field Infiltration Testing and Failure Diagnosis

Once an assembly's design has been approved, the practice verifies the installed work in the field. A `Consultant` schedules a field test by naming the `assembly_id`, the `test_method` — exactly one of `ASTM_E1105`, `ASTM_E783`, or `AAMA_502` — the planned `test_date`, and the `test_pressure_pa` chamber pressure differential, an integer of at least 50 and at most 1000 pascals. A field test carries two parallel status dimensions from creation: `execution_status` begins at `SCHEDULED`, and `diagnosis_status` begins at `NOT_REQUIRED`, a dimension that only engages when a test fails. The `result`, `measured_leakage_lps_m2`, `performed_by`, and `certified_by` fields are all unset at scheduling.

A `FieldTechnician` begins the test, moving `execution_status` from `SCHEDULED` to `IN_PROGRESS`. Beginning requires the engagement to be `IN_PROGRESS`, the posture to be other than `FROZEN` (`ERR_ENGAGEMENT_FROZEN`), and — critically — the tested assembly's `review_status` to be `APPROVED`; field-verifying an assembly whose design was never approved is rejected with `ERR_ASSEMBLY_NOT_APPROVED` (HTTP 409). The technician then records the outcome with the payload value `measured_leakage_lps_m2`, moving `execution_status` from `IN_PROGRESS` to `RESULT_RECORDED`. Recording stamps `performed_by` with the recording technician's `X-User-ID`, stores the measurement, and computes the `result`. The pass criterion is pressure-corrected: the assembly's `required_airtightness_lps_m2` is scaled linearly by the ratio of the test's `test_pressure_pa` to the 75-pascal reference pressure, and the measured leakage is compared against that allowable figure in exact decimal arithmetic with no rounding on either side. A measurement at most equal to the allowable — equality included — yields `PASS`; anything strictly greater yields `FAIL`.

A `FAIL` result sets off a cascade inside the same request. The test's `diagnosis_status` moves from `NOT_REQUIRED` to `UNDIAGNOSED`; the server automatically raises an Anomaly on the engagement with its `field_test_id` pointing at this test, `anomaly_type` `AIR_LEAKAGE`, `severity` `HIGH`, the description text "Auto-raised from failing field test", and status `OPEN`; the engagement's `risk_score` drops by 25, clamped at 0; and the engagement posture is re-derived — which, because an `OPEN` anomaly now exists, moves the posture to at least `RESTRICTED`. Any field-test transition invoked when the relevant dimension is in the wrong state is rejected with `ERR_FIELD_TEST_NOT_ACTIONABLE` (HTTP 409).

Diagnosis of a failed test is a `Consultant` workflow on the second dimension: beginning diagnosis moves `diagnosis_status` from `UNDIAGNOSED` to `DIAGNOSING`, and completing it moves from `DIAGNOSING` to `DIAGNOSED`. Certification is the `Principal`'s act, moving `execution_status` from `RESULT_RECORDED` to `CERTIFIED` and stamping `certified_by` with the certifying principal's `X-User-ID`. Certification enforces, in order: the posture must be other than `FROZEN` (`ERR_ENGAGEMENT_FROZEN`); the test must be in `RESULT_RECORDED` (`ERR_FIELD_TEST_NOT_ACTIONABLE`); segregation of duties must hold, meaning the certifier's `X-User-ID` must differ from the `performed_by` who recorded the result — a self-certified test is rejected with `ERR_DUTY_SEGREGATION_VIOLATION`; and when the `result` is `FAIL`, the `diagnosis_status` must have reached `DIAGNOSED`, otherwise `ERR_DIAGNOSIS_INCOMPLETE` (HTTP 409). A passing test may therefore be certified without any diagnosis, while a failing test cannot leave the books until its failure has been explained. Field-test lists can be filtered by `assembly_id`, and the anomalies raised against a given test can be read back through the flat listing route for that field test.

### 3.5. Thermal Imaging and Moisture Surveys

Surveys capture the non-destructive half of the diagnostic practice. A `Consultant` plans a survey by naming the `assembly_id`, the `survey_type` — exactly one of `THERMAL_IMAGING`, `MOISTURE`, or `COMBINED` — the planned `survey_date`, and the `ambient_delta_t_c`, the inside-to-outside temperature differential in degrees Celsius expected at scan time. The survey is created in `PLANNED` with its `anomaly_count` at 0.

A `FieldTechnician` completes the survey, moving it from `PLANNED` to `COMPLETED`. Completion requires the posture to be other than `FROZEN` (`ERR_ENGAGEMENT_FROZEN`) and, for the imaging modalities, a real thermal contrast: when the `survey_type` is `THERMAL_IMAGING` or `COMBINED`, the recorded `ambient_delta_t_c` must be at least 3.0 degrees Celsius, or completion is rejected with `ERR_IMAGING_DELTA_T_INSUFFICIENT` (HTTP 409). A pure `MOISTURE` survey carries no such condition. From `COMPLETED`, a `Consultant` moves the survey to the terminal `ANALYZED` state once the imagery has been interpreted. Alternatively, a `Consultant` may void a survey while it is still `PLANNED`, moving it to the terminal `VOID` state — for instance when weather or site access defeats the visit. Survey transitions invoked from the wrong state are rejected with `ERR_SURVEY_NOT_ACTIONABLE` (HTTP 409).

A survey's `anomaly_count` is a read-only figure maintained by the server: it counts the anomalies whose `survey_id` references this survey and whose status is anything other than `DISMISSED`. The count is recomputed when a survey-sourced anomaly is raised and again if such an anomaly is later dismissed. Survey lists can be filtered by `assembly_id`, and the anomalies raised against a given survey can be read back through the flat listing route for that survey.

### 3.6. Anomaly Triage and Risk Consequences

An **Anomaly** is the practice's unit of recorded deficiency. A `Consultant` raises one against exactly one parent: either the `field_test_id` of a field test or the `survey_id` of a survey. Supplying both, or neither, violates the parentage rule and is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The finding is classified by an `anomaly_type` of `WATER_INGRESS`, `AIR_LEAKAGE`, `THERMAL_BRIDGE`, or `MOISTURE_TRAP`, assigned a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, and described in free text through `description`. A new anomaly is `OPEN`, and raising one recomputes the parent survey's `anomaly_count` when the anomaly is survey-sourced, then re-derives the engagement posture — an engagement with any `OPEN` anomaly sits at no better than `RESTRICTED` under the derivation of §2.5.

Verification is the `Consultant`'s confirmation that the finding is real: it moves the anomaly from `OPEN` to `VERIFIED` and, at that moment, applies the severity-keyed risk delta of §2.6 — 15 points off the `risk_score` for `CRITICAL`, 10 for `HIGH`, 5 for `MEDIUM`, 2 for `LOW`, clamped to the 0-to-100 band — and re-derives posture. Verifying a critical anomaly is therefore one of the three ways an engagement freezes. Dismissal is the `Principal`'s prerogative: it moves the anomaly from `OPEN` to `DISMISSED`, recomputes the parent survey's `anomaly_count` (dismissed anomalies no longer count) when the anomaly is survey-sourced, and re-derives posture, which may relax the engagement back toward `OPEN` if no other open findings remain. Both actions require the anomaly to be `OPEN`; acting on an anomaly in any other state is rejected with `ERR_ANOMALY_NOT_OPEN` (HTTP 409).

The final exit, from `VERIFIED` to `REMEDIATED`, is not invoked directly by any user. It happens automatically, anomaly by anomaly, when a remediation plan covering the anomaly completes — the cascade is described in §3.7. Each anomaly so remediated returns 10 points to the engagement's `risk_score`, clamped at the ceiling of 100, with posture re-derived per anomaly. Anomaly lists can be filtered by `field_test_id` or by `survey_id` — supplying both filters returns only anomalies matching both — and the warranty claims filed against a given anomaly can be read back through the flat listing route for that anomaly.

### 3.7. Remediation Planning, Supersession, and Completion

When verified findings accumulate, the practice answers with a **RemediationPlan**. A `Consultant` drafts a plan by supplying a non-empty `anomaly_ids` list naming the anomalies the plan addresses, a non-empty `spec_sections` list of specification section strings, and — because drafting is one of the two concurrency-guarded writes of §2.9 — the engagement-version field `expected_engagement_version`. A stale version is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412), but only at the final validation tier of §2.11 — after the supersedes-target rule — so a create carrying both an invalid `supersedes_plan_id` and a stale version surfaces `ERR_SUPERSEDES_NOT_ISSUED`. The draft is created in `DRAFT`, with its `estimated_cost_cents` and `actual_cost_cents` left to be computed at issuance and completion respectively.

Drafting may deliberately replace an earlier plan. When the payload carries `supersedes_plan_id`, that reference must point to a remediation plan of the same engagement whose `plan_status` is currently `ISSUED`; anything else is rejected with `ERR_SUPERSEDES_NOT_ISSUED` (HTTP 409). A valid supersession flips the referenced plan from `ISSUED` to `SUPERSEDED` automatically as part of the create, reverses that plan's provisional recognition by subtracting its `estimated_cost_cents` from the engagement's `recognized_fees_cents`, re-derives the engagement posture, and — like every successful plan creation — increments the engagement's `version` by 1. The flat remediation-plan list accepts a `supersedes_plan_id` filter, which is how a reviewer traces which drafts were written to replace a given issued plan.

Issuance by a `Consultant` moves a plan from `DRAFT` to `ISSUED` and is the second concurrency-guarded write: the request again carries `expected_engagement_version`, and a mismatch with the engagement's current `version` is rejected with `ERR_STALE_ENGAGEMENT_VERSION`. Issuance further requires the plan to be `DRAFT` (otherwise `ERR_PLAN_NOT_ACTIONABLE`, HTTP 409), every anomaly named in `anomaly_ids` to be in `VERIFIED` status (otherwise `ERR_ANOMALY_NOT_VERIFIED`, HTTP 409), and the engagement posture to be exactly `OPEN` (otherwise `ERR_POSTURE_NOT_OPEN`). On issuance the server computes the **estimate variant** of the remediation cost into `estimated_cost_cents`: each listed anomaly contributes a base cost keyed to its severity — 500000 cents for `LOW`, 1500000 cents for `MEDIUM`, 4000000 cents for `HIGH`, and 9000000 cents for `CRITICAL` — the bases are summed into a subtotal, and a contingency multiplier of twenty percent is applied to that subtotal with the product rounded half-up to whole cents. The estimate variant carries no mobilization charge. The computed estimate is added to the engagement's `recognized_fees_cents` as provisional recognition, the engagement's `version` increments by 1, and posture is re-derived.

Completion is the `Principal`'s act and moves a plan from `ISSUED` to `COMPLETED`. It requires the plan to be `ISSUED` (`ERR_PLAN_NOT_ACTIONABLE`) and the posture to be other than `FROZEN` (`ERR_ENGAGEMENT_FROZEN`). Completion computes the **actual variant** of the remediation cost into `actual_cost_cents`: the same severity-keyed subtotal over the listed anomalies, with no contingency, plus a mobilization charge of 125000 cents for each specification section named in `spec_sections`. The engagement's recognized fees then absorb only the reconciliation delta — the actual cost minus the previously recognized estimate is added to `recognized_fees_cents`, a delta that may legitimately be negative when the work came in under estimate. In the same transaction, every anomaly named in `anomaly_ids` cascades from `VERIFIED` to `REMEDIATED`, each one returning 10 points to the `risk_score` (clamped at 100) and each triggering its own posture re-derivation, followed by a final posture derivation for the plan completion itself. A plan no longer wanted while still in `DRAFT` may be withdrawn by a `Consultant`, moving it from `DRAFT` to `WITHDRAWN` with no fiscal effect; any other withdrawal attempt fails with `ERR_PLAN_NOT_ACTIONABLE`.

### 3.8. Warranty Recovery and Manufacturer Coordination

Some verified deficiencies trace to a manufacturer's product, and the practice pursues recovery through a **WarrantyClaim**. A `Consultant` files a claim by naming the `anomaly_id` it pursues — the referenced anomaly must be `VERIFIED`, otherwise `ERR_ANOMALY_NOT_VERIFIED` — the `manufacturer_name` the claim is filed against, and the `claimed_amount_cents` sought, an integer of at least 1. Filing stamps `filed_at` with the current reading of the logical clock, computes `response_due_at` as exactly thirty days after `filed_at`, sets `recovered_amount_cents` to 0 while the claim is pending, and opens the claim with its `claim_status` at `FILED`.

The manufacturer's side of the conversation is conducted by a `ManufacturerRep`. Acknowledgement moves the claim from `FILED` to `UNDER_MANUFACTURER_REVIEW`. The decision action carries a `decision` payload of either `ACCEPTED` or `DENIED` and moves the claim accordingly, and it is valid from either `UNDER_MANUFACTURER_REVIEW` or `ESCALATED`; a decision attempted from any other state, or carrying a `decision` value other than those two, is rejected with `ERR_CLAIM_NOT_ACTIONABLE` (HTTP 409), while a missing or non-string `decision` field is a body-shape violation rejected with `ERR_INVALID_REQUEST` (HTTP 400).

A denied claim is not necessarily finished. A `Consultant` may escalate a claim from `DENIED` to `ESCALATED`, but only after the manufacturer's response window has fully elapsed: the logical clock must have reached the claim's `response_due_at` — the thirtieth day after filing — or the escalation is rejected with `ERR_ESCALATION_WINDOW_NOT_ELAPSED` (HTTP 409). After escalation the manufacturer decides again by the same decision action, and the cycle from `DENIED` to `ESCALATED` and back to `DENIED` may repeat.

Resolution is the `Consultant`'s final step, moving a claim from `ACCEPTED` to `RESOLVED` and computing the recovery through a fixed waterfall. First, gather the covering plans: every remediation plan of the engagement whose `plan_status` is `COMPLETED` and whose `anomaly_ids` contain the claim's anomaly. The outlay is the sum of those plans' `actual_cost_cents`, or 0 when no completed plan covers the anomaly. Second, subtract what that anomaly has already recovered: the sum of `recovered_amount_cents` over every other claim against the same anomaly that has already reached `RESOLVED`. The claim's `recovered_amount_cents` is then the smaller of the `claimed_amount_cents` and whatever remains of the outlay after prior recoveries — never less than 0, so a claim against an anomaly with no completed covering plan recovers nothing. Resolution subtracts the recovered amount from the engagement's `recognized_fees_cents`, flooring the recognized total at 0 so a recovery can never drive it negative, and re-derives the engagement posture. Claim lists can be filtered by `anomaly_id`.

### 3.9. Litigation Holds, the Maintenance Program, and Final Accounting

When a dispute turns legal, a `Principal` seals the engagement by applying a **LitigationHold** carrying a `matter_reference` string. The hold is created with its `hold_status` at `ACTIVE`; in the same act the engagement's `litigation_hold_active` flag becomes true, the posture derivation of §2.5 drives the engagement to `FROZEN`, and the engagement's `version` increments by 1. Releasing the hold, also a `Principal` act, moves it from `ACTIVE` to `RELEASED` — any other state is rejected with `ERR_HOLD_NOT_ACTIVE` (HTTP 409) — clears `litigation_hold_active` to false (assuming no other active hold), re-derives the posture so the engagement may thaw to `RESTRICTED` or `OPEN`, and increments the engagement's `version` by 1. A released hold remains as an immutable audit record; per §2.10 a LitigationHold carries only `id` and `created_at`, with no `updated_at` or `version` of its own.

The ongoing maintenance program is scheduled as **MaintenanceVisit** records. A `Consultant` schedules a visit with a human-readable `visit_label`, a `window_start_date`, a `window_end_date`, and an optional `buffer_days` defaulting to 0. The visit is created with its `visit_status` at `SCHEDULED`. The visit window is closed and inclusive: it spans from `window_start_date` through `window_end_date` including both endpoints, so `window_end_date` may equal but never precede `window_start_date`. Scheduling is rejected with `ERR_WINDOW_OVERLAP` when the new visit's closed window, expanded by `buffer_days` days on both sides, would intersect the closed window of any other visit still in `SCHEDULED` on the same engagement — and because both windows are closed, visits whose expanded windows merely touch at an endpoint day do conflict. A `FieldTechnician` completes a visit, moving it from `SCHEDULED` to `COMPLETED`, only when the logical clock's current date falls inside the closed window inclusive of both endpoints; outside the window the completion is rejected with `ERR_OUTSIDE_VISIT_WINDOW` (HTTP 409), and completing or cancelling a visit that is no longer `SCHEDULED` is rejected with `ERR_VISIT_NOT_SCHEDULED` (HTTP 409). A `Consultant` may instead cancel a scheduled visit, moving it from `SCHEDULED` to `CANCELLED`.

Billing runs through **Invoice** records drafted by a `Consultant` with the `labor_hours` worked (a number of at least 0), pass-through `expense_cents` (an integer of at least 0), and an optional `discount_pct` percentage defaulting to 0 and bounded between 0 and 100 inclusive. The invoice total is computed at creation in a pinned order: the labor line is `labor_hours` multiplied by the engagement's `labor_rate_cents_per_hour`, rounded half-up to whole cents, and the `subtotal_cents` is that figure plus `expense_cents`; the discount tier is then selected from the pre-discount subtotal — when `subtotal_cents` is at least 2000000 cents, the effective discount is the larger of the supplied `discount_pct` and 10 percent, and otherwise it is simply the supplied `discount_pct`; the `total_cents` is the subtotal reduced by the effective discount percentage, rounded half-up to whole cents. The invoice is created with its `invoice_status` at `DRAFT`, and like a LitigationHold it carries only `id` and `created_at` — no `updated_at`, no `version`.

Issuing an invoice, a `Consultant` act, moves it from `DRAFT` to `ISSUED`. Issuance requires the invoice to be `DRAFT` (otherwise `ERR_INVOICE_NOT_DRAFT`, HTTP 409), the posture to be other than `FROZEN` (`ERR_ENGAGEMENT_FROZEN`), and — the fiscal gate of §2.7 — the engagement's `fee_headroom_cents` to be at least the invoice's `total_cents` (otherwise `ERR_FEE_CAP_EXCEEDED`, HTTP 402). On issuance the engagement's `invoiced_cents` is recomputed as the sum of `total_cents` over invoices in `ISSUED` or `PAID`. A `Principal` marks an issued invoice paid, moving it from `ISSUED` to `PAID` (`ERR_INVOICE_NOT_ISSUED` when it is not `ISSUED`) and recomputing `invoiced_cents` again. A `Consultant` may instead void a draft invoice, moving it from `DRAFT` to `VOID`.

The engagement's own endgame has two gates. Beginning close-out, a `Principal` act, moves the engagement from `IN_PROGRESS` to `CLOSE_OUT` and enforces three clean-slate conditions: no anomaly of the engagement remains in `OPEN` or `VERIFIED` (otherwise `ERR_OPEN_ANOMALIES_REMAIN`, HTTP 409); every field test has reached `CERTIFIED` (otherwise `ERR_UNCERTIFIED_TESTS_REMAIN`, HTTP 409); and no design review round remains in `SUBMITTED`, `UNDER_REVIEW`, `COMMENTS_ISSUED`, or `REVISED` (otherwise `ERR_OPEN_REVIEWS_REMAIN`, HTTP 409). An engagement that is not `IN_PROGRESS` cannot begin close-out at all (`ERR_ENGAGEMENT_NOT_IN_PROGRESS`). This transition runs the **final** fee-accrual variant of §2.7 — the chronological replay of positive fee events only, warranty recoveries excluded, no intermediate floor — replacing the provisional `recognized_fees_cents` with the definitive figure, and it is the sole moment when `fee_headroom_cents` may go negative. The engagement's `version` increments by 1. Final closure, again a `Principal` act, moves the engagement from `CLOSE_OUT` to `CLOSED`; it requires the engagement to be in `CLOSE_OUT` (otherwise `ERR_ENGAGEMENT_NOT_CLOSING_OUT`, HTTP 409), every invoice to be `PAID` or `VOID` (otherwise `ERR_UNPAID_INVOICES_REMAIN`, HTTP 409), and every warranty claim to be `RESOLVED` (otherwise `ERR_UNRESOLVED_CLAIMS_REMAIN`, HTTP 409). Closure increments the engagement's `version` by 1, and `CLOSED` is terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or merely read data return `200 OK`. Request and response payloads for every operation are defined by the workflows of §3 rather than repeated here. In the table below, "Any" in the role column means all five roles (`Principal`, `Consultant`, `Reviewer`, `FieldTechnician`, `ManufacturerRep`) are authorized.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical server clock | Principal |
| POST | `/engagements` | Create an engagement | Principal |
| GET | `/engagements` | List engagements | Any |
| GET | `/engagements/{id}` | Get an engagement, including computed posture, headroom, and recognized/invoiced fees | Any |
| POST | `/engagements/{id}/activate` | Activate an engagement (`SETUP` → `IN_PROGRESS`) | Principal |
| POST | `/engagements/{id}/begin-close-out` | Begin close-out (`IN_PROGRESS` → `CLOSE_OUT`); runs the final fee accrual | Principal |
| POST | `/engagements/{id}/close` | Close the engagement (`CLOSE_OUT` → `CLOSED`) | Principal |
| POST | `/engagements/{id}/assemblies` | Create an assembly | Consultant |
| GET | `/engagements/{id}/assemblies` | List assemblies of an engagement | Any |
| GET | `/engagements/{id}/assemblies/{assemblyId}` | Get an assembly | Any |
| POST | `/engagements/{id}/design-reviews` | Submit a design review for an assembly | Consultant |
| GET | `/engagements/{id}/design-reviews` | List design reviews (filterable by `assembly_id`) | Any |
| GET | `/engagements/{id}/design-reviews/{reviewId}` | Get a design review | Any |
| POST | `/engagements/{id}/design-reviews/{reviewId}/start-review` | Start a review round (`SUBMITTED` or `REVISED` → `UNDER_REVIEW`) | Reviewer |
| POST | `/engagements/{id}/design-reviews/{reviewId}/issue-comments` | Issue comments (`UNDER_REVIEW` → `COMMENTS_ISSUED`) | Reviewer |
| POST | `/engagements/{id}/design-reviews/{reviewId}/submit-revision` | Submit a revision (`COMMENTS_ISSUED` → `REVISED`) | Consultant |
| POST | `/engagements/{id}/design-reviews/{reviewId}/approve` | Approve a round (`UNDER_REVIEW` → `APPROVED`); accrues the review fee | Reviewer |
| POST | `/engagements/{id}/design-reviews/{reviewId}/reject` | Reject a round (`UNDER_REVIEW` → `REJECTED`); accrues the review fee | Reviewer |
| POST | `/engagements/{id}/chamber-slots` | Reserve a chamber window (half-open); same-chamber overlap rejected | Consultant |
| GET | `/engagements/{id}/chamber-slots` | List chamber slots | Any |
| GET | `/engagements/{id}/chamber-slots/{slotId}` | Get a chamber slot | Any |
| POST | `/engagements/{id}/chamber-slots/{slotId}/release` | Release a reserved slot (only when no live mock-up references it) | Consultant |
| POST | `/engagements/{id}/mock-ups` | Create a mock-up bound to an assembly and a chamber slot | Consultant |
| GET | `/engagements/{id}/mock-ups` | List mock-ups (filterable by `assembly_id`) | Any |
| GET | `/engagements/{id}/mock-ups/{mockUpId}` | Get a mock-up | Any |
| POST | `/engagements/{id}/mock-ups/{mockUpId}/begin-construction` | Begin construction (`PLANNED` → `CONSTRUCTING`) | Consultant |
| POST | `/engagements/{id}/mock-ups/{mockUpId}/declare-ready` | Declare the rig built (`CONSTRUCTING` → `READY_FOR_TEST`) | Consultant |
| POST | `/engagements/{id}/mock-ups/{mockUpId}/begin-testing` | Begin testing (`READY_FOR_TEST` or `REMEDIATED` → `TESTING`); consumes the bound slot | Consultant |
| POST | `/engagements/{id}/mock-ups/{mockUpId}/record-result` | Record the leakage result (`TESTING` → `PASSED` or `FAILED`; equality passes) | Consultant |
| POST | `/engagements/{id}/mock-ups/{mockUpId}/mark-remediated` | Mark a failed rig remediated (`FAILED` → `REMEDIATED`) | Consultant |
| POST | `/engagements/{id}/field-tests` | Schedule a field test | Consultant |
| GET | `/engagements/{id}/field-tests` | List field tests (filterable by `assembly_id`) | Any |
| GET | `/engagements/{id}/field-tests/{fieldTestId}` | Get a field test | Any |
| POST | `/engagements/{id}/field-tests/{fieldTestId}/begin` | Begin a field test (`SCHEDULED` → `IN_PROGRESS`); assembly must be approved | FieldTechnician |
| POST | `/engagements/{id}/field-tests/{fieldTestId}/record-result` | Record the result (`IN_PROGRESS` → `RESULT_RECORDED`); computes pass/fail | FieldTechnician |
| POST | `/engagements/{id}/field-tests/{fieldTestId}/begin-diagnosis` | Begin failure diagnosis (`UNDIAGNOSED` → `DIAGNOSING`) | Consultant |
| POST | `/engagements/{id}/field-tests/{fieldTestId}/complete-diagnosis` | Complete failure diagnosis (`DIAGNOSING` → `DIAGNOSED`) | Consultant |
| POST | `/engagements/{id}/field-tests/{fieldTestId}/certify` | Certify the result (`RESULT_RECORDED` → `CERTIFIED`); certifier differs from performer | Principal |
| POST | `/engagements/{id}/surveys` | Plan a thermal-imaging or moisture survey | Consultant |
| GET | `/engagements/{id}/surveys` | List surveys (filterable by `assembly_id`) | Any |
| GET | `/engagements/{id}/surveys/{surveyId}` | Get a survey | Any |
| POST | `/engagements/{id}/surveys/{surveyId}/complete` | Complete a survey (`PLANNED` → `COMPLETED`); delta-T rule for imaging types | FieldTechnician |
| POST | `/engagements/{id}/surveys/{surveyId}/analyze` | Mark a survey analyzed (`COMPLETED` → `ANALYZED`) | Consultant |
| POST | `/engagements/{id}/surveys/{surveyId}/void` | Void a planned survey (`PLANNED` → `VOID`) | Consultant |
| POST | `/engagements/{id}/anomalies` | Raise an anomaly against exactly one of a field test or a survey | Consultant |
| GET | `/engagements/{id}/anomalies` | List anomalies (filterable by `field_test_id` or `survey_id`) | Any |
| GET | `/engagements/{id}/anomalies/{anomalyId}` | Get an anomaly | Any |
| POST | `/engagements/{id}/anomalies/{anomalyId}/verify` | Verify an anomaly (`OPEN` → `VERIFIED`); applies the severity risk delta | Consultant |
| POST | `/engagements/{id}/anomalies/{anomalyId}/dismiss` | Dismiss an anomaly (`OPEN` → `DISMISSED`) | Principal |
| POST | `/engagements/{id}/remediation-plans` | Create a remediation plan (OCC-guarded; supersedes an issued plan when directed) | Consultant |
| GET | `/engagements/{id}/remediation-plans` | List remediation plans | Any |
| GET | `/engagements/{id}/remediation-plans/{planId}` | Get a remediation plan | Any |
| POST | `/engagements/{id}/remediation-plans/{planId}/issue` | Issue a plan (`DRAFT` → `ISSUED`; OCC-guarded; computes the estimate) | Consultant |
| POST | `/engagements/{id}/remediation-plans/{planId}/complete` | Complete a plan (`ISSUED` → `COMPLETED`; computes the actual cost and remediates covered anomalies) | Principal |
| POST | `/engagements/{id}/remediation-plans/{planId}/withdraw` | Withdraw a draft plan (`DRAFT` → `WITHDRAWN`) | Consultant |
| POST | `/engagements/{id}/warranty-claims` | File a warranty claim against a verified anomaly | Consultant |
| GET | `/engagements/{id}/warranty-claims` | List warranty claims (filterable by `anomaly_id`) | Any |
| GET | `/engagements/{id}/warranty-claims/{claimId}` | Get a warranty claim | Any |
| POST | `/engagements/{id}/warranty-claims/{claimId}/manufacturer-acknowledge` | Manufacturer acknowledges (`FILED` → `UNDER_MANUFACTURER_REVIEW`) | ManufacturerRep |
| POST | `/engagements/{id}/warranty-claims/{claimId}/manufacturer-decide` | Manufacturer decides (`UNDER_MANUFACTURER_REVIEW` or `ESCALATED` → `ACCEPTED` or `DENIED`) | ManufacturerRep |
| POST | `/engagements/{id}/warranty-claims/{claimId}/escalate` | Escalate a denied claim after the response window elapses (`DENIED` → `ESCALATED`) | Consultant |
| POST | `/engagements/{id}/warranty-claims/{claimId}/resolve` | Resolve an accepted claim (`ACCEPTED` → `RESOLVED`); computes the recovery share | Consultant |
| POST | `/engagements/{id}/litigation-holds` | Apply a litigation hold (posture freezes) | Principal |
| GET | `/engagements/{id}/litigation-holds` | List litigation holds | Any |
| GET | `/engagements/{id}/litigation-holds/{holdId}` | Get a litigation hold | Any |
| POST | `/engagements/{id}/litigation-holds/{holdId}/release` | Release a hold (`ACTIVE` → `RELEASED`); thaws posture | Principal |
| POST | `/engagements/{id}/maintenance-visits` | Schedule a maintenance visit (closed window; buffer-expanded overlap check) | Consultant |
| GET | `/engagements/{id}/maintenance-visits` | List maintenance visits | Any |
| GET | `/engagements/{id}/maintenance-visits/{visitId}` | Get a maintenance visit | Any |
| POST | `/engagements/{id}/maintenance-visits/{visitId}/complete` | Complete a visit (`SCHEDULED` → `COMPLETED`); clock must be inside the window | FieldTechnician |
| POST | `/engagements/{id}/maintenance-visits/{visitId}/cancel` | Cancel a visit (`SCHEDULED` → `CANCELLED`) | Consultant |
| POST | `/engagements/{id}/invoices` | Create a draft invoice; the total is computed at creation | Consultant |
| GET | `/engagements/{id}/invoices` | List invoices | Any |
| GET | `/engagements/{id}/invoices/{invoiceId}` | Get an invoice | Any |
| POST | `/engagements/{id}/invoices/{invoiceId}/issue` | Issue an invoice (`DRAFT` → `ISSUED`; headroom check) | Consultant |
| POST | `/engagements/{id}/invoices/{invoiceId}/mark-paid` | Mark an invoice paid (`ISSUED` → `PAID`) | Principal |
| POST | `/engagements/{id}/invoices/{invoiceId}/void` | Void a draft invoice (`DRAFT` → `VOID`) | Consultant |
| GET | `/assemblies/{id}` | Get an assembly by id (flat alias) | Any |
| GET | `/assemblies/{id}/design-reviews` | List design reviews of an assembly | Any |
| GET | `/assemblies/{id}/mock-ups` | List mock-ups of an assembly | Any |
| GET | `/assemblies/{id}/field-tests` | List field tests of an assembly | Any |
| GET | `/assemblies/{id}/surveys` | List surveys of an assembly | Any |
| GET | `/chamber-slots/{id}` | Get a chamber slot by id (flat alias) | Any |
| GET | `/chamber-slots/{id}/mock-ups` | List mock-ups bound to a chamber slot | Any |
| GET | `/field-tests/{id}` | Get a field test by id (flat alias) | Any |
| GET | `/field-tests/{id}/anomalies` | List anomalies raised against a field test | Any |
| GET | `/surveys/{id}` | Get a survey by id (flat alias) | Any |
| GET | `/surveys/{id}/anomalies` | List anomalies raised against a survey | Any |
| GET | `/anomalies/{id}` | Get an anomaly by id (flat alias) | Any |
| GET | `/anomalies/{id}/warranty-claims` | List warranty claims filed against an anomaly | Any |
| GET | `/remediation-plans/{id}` | Get a remediation plan by id (flat alias) | Any |
| GET | `/remediation-plans` | List remediation plans (filterable by `supersedes_plan_id`) | Any |

## 5. Error Code Catalogue

The trigger condition for each error is defined in the narrative of §2 and §3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ENGAGEMENT_NOT_IN_SETUP` | 409 |
| `ERR_ENGAGEMENT_NOT_IN_PROGRESS` | 409 |
| `ERR_ENGAGEMENT_NOT_CLOSING_OUT` | 409 |
| `ERR_ENGAGEMENT_FROZEN` | 409 |
| `ERR_POSTURE_NOT_OPEN` | 409 |
| `ERR_OPEN_ANOMALIES_REMAIN` | 409 |
| `ERR_UNCERTIFIED_TESTS_REMAIN` | 409 |
| `ERR_OPEN_REVIEWS_REMAIN` | 409 |
| `ERR_UNPAID_INVOICES_REMAIN` | 409 |
| `ERR_UNRESOLVED_CLAIMS_REMAIN` | 409 |
| `ERR_DUPLICATE_ASSEMBLY_TAG` | 409 |
| `ERR_REVIEW_NOT_ACTIONABLE` | 409 |
| `ERR_DUTY_SEGREGATION_VIOLATION` | 403 |
| `ERR_MOCKUP_NOT_ACTIONABLE` | 409 |
| `ERR_SLOT_NOT_RESERVED` | 409 |
| `ERR_SLOT_IN_USE` | 409 |
| `ERR_OUTSIDE_SLOT_WINDOW` | 409 |
| `ERR_FIELD_TEST_NOT_ACTIONABLE` | 409 |
| `ERR_ASSEMBLY_NOT_APPROVED` | 409 |
| `ERR_DIAGNOSIS_INCOMPLETE` | 409 |
| `ERR_SURVEY_NOT_ACTIONABLE` | 409 |
| `ERR_IMAGING_DELTA_T_INSUFFICIENT` | 409 |
| `ERR_ANOMALY_NOT_OPEN` | 409 |
| `ERR_ANOMALY_NOT_VERIFIED` | 409 |
| `ERR_PLAN_NOT_ACTIONABLE` | 409 |
| `ERR_SUPERSEDES_NOT_ISSUED` | 409 |
| `ERR_STALE_ENGAGEMENT_VERSION` | 412 |
| `ERR_CLAIM_NOT_ACTIONABLE` | 409 |
| `ERR_ESCALATION_WINDOW_NOT_ELAPSED` | 409 |
| `ERR_HOLD_NOT_ACTIVE` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_VISIT_NOT_SCHEDULED` | 409 |
| `ERR_OUTSIDE_VISIT_WINDOW` | 409 |
| `ERR_INVOICE_NOT_DRAFT` | 409 |
| `ERR_INVOICE_NOT_ISSUED` | 409 |
| `ERR_FEE_CAP_EXCEEDED` | 402 |
