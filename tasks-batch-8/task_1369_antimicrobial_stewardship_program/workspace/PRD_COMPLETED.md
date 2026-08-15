# Antimicrobial Stewardship Program API — Product Requirements Document

## 1. Introduction

Antimicrobial resistance is a standing agenda item for every hospital quality committee, and the stewardship program is the operational arm that turns policy into daily practice: gating restricted antibiotics behind expert approval, auditing therapy prospectively, pushing de-escalation and IV-to-oral conversion where the evidence supports it, delabeling spurious penicillin allergies, and reporting consumption to regulators. This document specifies the API that a hospital's stewardship committee uses to run that program end to end — from registering the formulary and admitting patient cases, through the negotiation loop between auditors and prescribers, to antibiogram publication, empiric-guideline governance, days-of-therapy benchmarking, and formal regulatory submission.

The API is organized on a single-facility scope: every resource belongs to a hospital, and every clinical judgment the system makes is anchored to that hospital's configurable thresholds and to a hospital-scoped logical clock that governs expiry, deadlines, and period boundaries. Roles mirror the real committee — prescribers, infectious-diseases pharmacists, the microbiology laboratory, infection prevention, and a physician director — with segregation-of-duties rules that prevent any one actor from approving, adjudicating, or withdrawing work they themselves authored. All endpoints are mounted under the `/stewardship` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply uniformly to every endpoint in the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` declares their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly six roles, spelled as follows: `StewardshipAdmin`, `StewardshipDirector`, `IDPharmacist`, `AttendingPhysician`, `Microbiologist`, and `InfectionPreventionist`. Access to each operation is restricted by role per the endpoint catalogue in §4; an authenticated caller whose role is not on an endpoint's authorized list is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. A well-formed `X-User-Role` header whose value is not one of the six recognized roles is likewise rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

Role identity is resolved in two distinct ways, and the distinction matters wherever a resource records who acted on it. When `X-User-Role` is `StewardshipAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may log it but never compares it against a practitioner's `id`. When `X-User-Role` is `StewardshipDirector`, `IDPharmacist`, `AttendingPhysician`, `Microbiologist`, or `InfectionPreventionist`, `X-User-ID` is the `id` of the acting `Practitioner`, and every ownership or segregation check on a resource that references a practitioner — `requester_id`, `decided_by_id`, `auditor_id`, `responded_by_id`, `appeal_adjudicator_id`, `prescriber_id` — compares that resource field to `X-User-ID`. Acting through an entity-backed role while the referenced practitioner record is inactive is rejected wherever a practitioner reference is supplied, per the guardrail cascade in §2.8.

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
- Requests to undefined paths, or to defined paths with an unsupported method, are rejected with `ERR_NOT_FOUND` (404) in the same envelope; a request body that is not valid JSON or not a JSON object is rejected with `ERR_INVALID_REQUEST`.

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, and values below 1 or above 100 are out of range — the minimum is 1 and the maximum is 100; a non-integer or out-of-range `limit`, or a negative or non-integer `offset`, is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter states how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by `id`. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Program Clock: Logical Time and Scheduled Sweeps

Every hospital runs on its own logical clock, exposed as the `current_utc` field on the `Hospital` resource. The clock starts at exactly 2026-08-01T00:00:00Z when the hospital is created, never falls back to wall-clock time, and advances only through an explicit clock-advance capability available to `StewardshipDirector` and `StewardshipAdmin`. That capability takes the target `hospital_id` and a destination instant `to_iso8601`; the destination must be strictly later than the hospital's present `current_utc`, and any attempt to hold or move the clock backwards is rejected with `ERR_CLOCK_REGRESSION`. All deadline arithmetic in the program — approval expiry, intervention response windows, opportunity staleness, period closures — reads this logical clock, never the server's wall clock. Advancing the clock refreshes the hospital's `updated_at` but deliberately does not increment its `version`. Timestamps stamped from the logical clock (`submitted_at`, `due_at`, `stopped_at`, and the like) serialize in the precision style of the most recent clock-set: bare seconds by default, or three fractional digits when the last `to_iso8601` carried fractional digits.

Advancing the clock fires four scheduled sweeps, applied hospital-wide before the capability returns. First, any approval request still in `SUBMITTED` whose age has reached the hospital's `restricted_auto_expire_hours` transitions to `EXPIRED`, with the order-level cascade described in §3.2. Second, any audit intervention still in `RECOMMENDED` whose `due_at` has passed transitions to `SUPERSEDED`. Third, any conversion opportunity still in `DETECTED` more than 48 hours after its `detected_at` transitions to `EXPIRED`. Fourth, any order in `ACTIVE` whose `dot_calendar` has reached the hospital's `dot_review_threshold` is flagged `REVIEW_REQUIRED`, making it eligible as an audit target.

### 2.5. Common Resource Properties

Every primary resource in the system — hospitals, practitioners, patient cases, antimicrobials, allergy assessments, culture reports, susceptibility results, antibiotic orders, approval requests, audit interventions, conversion opportunities, antibiograms, antibiogram rows, empiric guidelines, DOT metric snapshots, and regulatory reports — carries the same four system-managed fields:

- **`id`** (string): a unique, server-minted UUID with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, stamped from the server's wall clock — never from the hospital's logical clock of §2.4, which does not feed this field.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation of the resource, likewise stamped from the server's wall clock rather than the logical clock.
- **`version`** (integer): a system-managed integer that increments by one on every mutation, including mutations applied by automatic cascades rather than direct client writes (the clock advance of §2.4 is the standing exception — it refreshes `updated_at` without incrementing `version`).

When an operation mutates more than one resource — for example a decision that moves both an approval request and its parent order — each mutated resource independently refreshes its `updated_at` and increments its `version`.

### 2.6. Measurement Precision and Rounding

All rates, scores, and dose-normalized metrics in the program are decimal quantities carried to exactly 2 decimal places using round-half-up: the penicillin allergy `risk_score`, the IV-to-PO `eligibility_score`, each order's `dot_dose`, each snapshot's `total_dot_dose`, `dot_per_1000_pd_calendar`, and `dot_per_1000_pd_dose`, and every antibiogram row's `pct_susceptible` together with a guideline's `pct_susceptible_at_adoption` snapshot. Pure counts are integers with no fractional component: `dot_calendar`, `administered_doses`, `cumulative_iv_hours`, `isolate_count`, `susceptible_count`, `row_count`, `total_dot_calendar`, `patient_days`, and `unresolved_noncompliance_count`. A snapshot's `benchmark_percentile` is an integer drawn only from the set {10, 25, 50, 75, 90}, and a de-escalation opportunity's `eligibility_score` is likewise an integer. No computed quantity in the API is ever truncated or left at full floating-point precision. In JSON serialization, any of these two-decimal quantities whose value is integral renders as a bare integer (for example 3.00 renders as 3).

### 2.7. Optimistic Concurrency Control on Hospital Posture

Two write operations change hospital-wide clinical posture and therefore carry optimistic concurrency protection: publishing an antibiogram and adopting an empiric guideline. Each of these requests must include `expected_hospital_version`, a non-optional input carrying the `version` of the `Hospital` resource as the client last observed it. If the hospital's current `version` has advanced beyond that observed value, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), because the caller would otherwise be publishing against — or adopting onto — a baseline they have not seen. Omitting `expected_hospital_version` or supplying a non-integer value is rejected with `ERR_INVALID_REQUEST`. Both operations increment the hospital's `version` by one on success. No endpoint other than these two accepts or requires a version field.

### 2.8. The Validation Cascade and Its Order

Every request passes through a fixed validation cascade, and the order is part of the contract: when several checks would fail, the caller sees the error from the earliest failing stage. The stages run as follows.

1. **Authentication context** — both headers present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Authorization** — the caller's role is on the endpoint's authorized list, else `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Existence** — path-referenced resources exist, validated left to right, else `ERR_NOT_FOUND` (see §2.11).
4. **Referenced-state checks** — a referenced practitioner must be active (`ERR_PRACTITIONER_INACTIVE`); a referenced patient must still be admitted for any order, culture, or assessment mutation (`ERR_PATIENT_DISCHARGED`); a referenced antimicrobial must be formulary-active for a new order or a culture-driven recommendation (`ERR_DRUG_SUSPENDED`).
5. **Clinical safety gates** — the penicillin allergy block on ordering (`ERR_ALLERGY_BLOCKS_ORDER`), the renal dosing guardrail (`ERR_RENAL_DOSE_EXCEEDED`), the severe-allergy testing block (`ERR_SEVERE_ALLERGY_BLOCKED`), and the two segregation-of-duties checks (`ERR_SELF_APPROVAL_FORBIDDEN`, `ERR_ADJUDICATOR_CONFLICT`).
6. **Temporal rules** — specimen collection not in the future (`ERR_FUTURE_SPECIMEN`), intervention response before its deadline (`ERR_INTERVENTION_OVERDUE`), antibiogram period validity (`ERR_INVALID_PERIOD`) and window overlap (`ERR_ANTIBIOGRAM_WINDOW_OVERLAP`), allergy rechallenge timing (`ERR_RECHALLENGE_TOO_EARLY`), and snapshot period closure (`ERR_PERIOD_NOT_CLOSED`).
7. **Referential integrity** — cross-facility references (`ERR_CROSS_FACILITY_REFERENCE`), approval-request target state (`ERR_ORDER_APPROVAL_NOT_PENDING`), guideline source antibiogram posture (`ERR_ANTIBIOGRAM_NOT_PUBLISHED`), supersession validity (`ERR_INVALID_SUPERSESSION`), and pinned-snapshot posture (`ERR_SNAPSHOT_NOT_FINAL`).
8. **Business constraints** — the restricted-approval requirement before administration (`ERR_RESTRICTED_REQUIRES_APPROVAL`), duplicate active orders (`ERR_DUPLICATE_ACTIVE_ORDER`), the concurrent restricted-order cap (`ERR_RESTRICTED_ORDER_CAP`), antibiogram row uniqueness (`ERR_DUPLICATE_ROW`), single open approval request per order (`ERR_APPROVAL_ALREADY_OPEN`), snapshot period uniqueness (`ERR_DUPLICATE_SNAPSHOT_PERIOD`), and report uniqueness (`ERR_REPORT_ALREADY_SUBMITTED`).
9. **Threshold and standing checks** — the first-line susceptibility floor at guideline adoption (`ERR_FIRST_LINE_BELOW_THRESHOLD`) and the suspended-prescriber block on restricted ordering (`ERR_PRESCRIBER_SUSPENDED`).
10. **Eligibility scoring** — the opportunity-detection gate, rejecting with `ERR_CONVERSION_NOT_ELIGIBLE` or `ERR_DEESCALATION_NOT_ELIGIBLE` when a hard gate fails or the computed score falls below its floor.

Within a single endpoint, this ordering means, for example, that a missing header surfaces before any 404, an inactive practitioner surfaces before a discharged patient, the allergy and renal safety checks on ordering fire before the cross-facility reference check, and the duplicate-order and cap constraints fire before the prescriber-suspension check. State-machine-specific guards (a request not pending, a snapshot not open, and so on) are evaluated with the workflow and carry the workflow's own error identifiers as narrated in §3. Field-shape failures — a missing required field, a wrong type, an out-of-range enum, or a string below its minimum length — are rejected with `ERR_INVALID_REQUEST`; creation endpoints run these checks before resolving body-referenced resources, while action endpoints run them at the point each field is consumed, which may be after the workflow-state guard.

### 2.9. Segregation of Duties on the Committee

The program enforces four standing separations so that no clinical judgment is both made and ratified by the same hand. A practitioner who submitted a restricted-drug approval request may not decide it: any decision where the decider equals the `requester_id` is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`. A committee member adjudicating an appealed audit intervention must be neither the auditor who wrote it nor the prescriber who responded to it: a violation is rejected with `ERR_ADJUDICATOR_CONFLICT`. Withdrawing an approval request is reserved to the practitioner who submitted it (`ERR_NOT_REQUEST_OWNER`), and responding to an issued intervention is reserved to the order's own prescriber (`ERR_NOT_PRESCRIBER`). A fifth separation governs escalation: once an approval request has been escalated, only the `StewardshipDirector` may decide it, and any other decider is rejected with `ERR_ESCALATED_REQUIRES_DIRECTOR`. Finally, only the auditor who authored a rejected intervention may appeal it (`ERR_NOT_AUDIT_OWNER`).

### 2.10. Single-Facility Scope and Cross-Facility References

Every clinical entity is scoped to exactly one hospital, and references that cross facility boundaries are rejected with `ERR_CROSS_FACILITY_REFERENCE`. The rule bites in three principal places: a susceptibility row's `antimicrobial_id` must reference a drug on the same hospital's formulary as the patient whose culture it annotates; an antibiotic order's patient, drug, and prescriber must all belong to the same hospital; and an empiric guideline's source antibiogram must belong to the hospital the guideline governs. A regulatory report likewise pins a snapshot of its own hospital whose period label matches the report's coverage month, enforced through the pinned-snapshot posture check.

### 2.11. Nested Path Resolution

Where an endpoint path contains multiple identifiers — for example a susceptibility row beneath a culture report, or an action beneath an order — the server validates existence strictly left to right. The first path segment that does not resolve to an existing resource produces an immediate `ERR_NOT_FOUND`, and no later segment or body validation runs. An action on a child of a missing parent therefore reports the missing parent, never a validation error from deeper in the request.

## 3. Business Logic & Workflows

### 3.1. Program Setup: Facilities, Practitioners, Patients, and the Formulary

Before any clinical workflow can run, a `StewardshipAdmin` establishes the program's scope by creating a hospital with a `name` and the `nhsn_facility_id` that will later identify the facility on regulatory reports. Four configurable thresholds govern the hospital's stewardship posture, each with a default and a floor: `dot_review_threshold` is the days-of-therapy length, in whole days, at or above which an active order is flagged for mandatory prospective audit — it defaults to 7 and must be at least 1; `iv_to_po_min_iv_hours` is the minimum cumulative IV exposure before a conversion opportunity may be raised — it defaults to 48 and must be at least 24; `antibiogram_min_isolates` is the minimum first-isolate count for a susceptibility row to be reportable — it defaults to 30 and must be at least 1; and `restricted_auto_expire_hours` is the number of hours a submitted approval request may sit undecided before the clock sweep expires it — it defaults to 72 and must be at least 1. The hospital's `current_utc` begins at 2026-08-01T00:00:00Z, and the usual `id`, `created_at`, `updated_at`, and `version` machinery applies from that moment.

Practitioners join the program through admin registration, which records the `hospital_id` they practice at, a `full_name`, a `license_no` unique within the hospital by convention (the server does not enforce uniqueness), and a `discipline` drawn from `PHYSICIAN`, `PHARMACIST`, `MICROBIOLOGIST`, or `INFECTION_PREVENTIONIST`. The optional `is_stewardship_member` flag (default false) records committee membership. Every practitioner starts with `is_active` true, a `stewardship_standing` of `GOOD`, and an `unresolved_noncompliance_count` of zero; the standing later derives from resolved interventions, as §3.3 describes. An administrator may subsequently patch `is_active` (deactivation) or `is_stewardship_member`; each patch that supplies at least one of the two fields increments the practitioner's `version` (even when the supplied value equals the current one), while a patch supplying neither leaves the record untouched. Any workflow that references a practitioner — as prescriber, requester, decider, auditor, responder, or adjudicator — requires `is_active` to still be true, and rejects an inactive reference with `ERR_PRACTITIONER_INACTIVE`.

Patient intake is shared among `AttendingPhysician`, `IDPharmacist`, and `StewardshipAdmin`. Admitting a case records the admitting `hospital_id`, an `mrn` unique within that hospital by convention (uniqueness is not server-enforced), the caller-supplied `admitted_at` timestamp (expected to be the logical-clock time at registration, and recorded verbatim), the `ward` code, the measured `weight_kg` (strictly greater than zero), the `renal_function_crcl` in mL/min (zero or greater), and two flags that modulate downstream thresholds: `is_immunocompromised` (default false) and `has_enteral_access` (default true). A case opens with `status` `ADMITTED`. Discharge — an `AttendingPhysician` action — moves the case to `DISCHARGED` and locks the chart in one pass: every order not yet in a terminal therapy state is moved to `COMPLETED` with `stopped_at` stamped from the clock, and every intervention still in `DOCUMENTED` or `RECOMMENDED` is moved to `SUPERSEDED`. Discharge does not alter any order's `approval_status`, and discharging an already-discharged case simply re-applies the same cascade. Once a case is discharged, any attempt to mutate its orders, cultures, or allergy assessments is rejected with `ERR_PATIENT_DISCHARGED`.

The formulary is maintained by `StewardshipAdmin` and `IDPharmacist`. Adding a drug records its `hospital_id`, a `drug_name` unique within the hospital by convention (not server-enforced), a `drug_class` (the program recognizes classes such as `CARBAPENEM`, `GLYCOPEPTIDE`, `FLUOROQUINOLONE`, and `BETA_LACTAM`, among others), and three booleans that drive entire subsystems: `is_restricted` marks drugs that require committee approval before the first dose; `has_po_form` marks drugs with an oral formulation of equivalent bioavailability, gating IV-to-PO candidacy; and `is_penicillin_class` (default false) marks penicillins and cross-reactive beta-lactams, gating the allergy-delabeling workflow. A drug enters with `formulary_status` `ACTIVE`; suspending it via a patch to `formulary_status` moves it to `SUSPENDED` (the same patch reactivates a suspended drug to `ACTIVE`, and a patch that does not change the value leaves the drug's `version` untouched), after which new orders and new culture-driven recommendations involving it are refused — an order attempt against a suspended drug fails with `ERR_DRUG_SUSPENDED`, while the recommendation selector of §3.4 simply excludes suspended drugs from its candidate pool.

### 3.2. Ordering Therapy and the Restricted-Drug Approval Gate

An `AttendingPhysician` places an antibiotic order with a payload naming the `patient_case_id`, the `antimicrobial_id`, the `prescriber_id`, the administration `route` (one of `IV`, `PO`, or `IM`), the per-dose `dose_mg` (an integer strictly greater than zero), the `frequency_per_day` (between 1 and 4 doses per calendar day), and the `indication` — `EMPIRIC`, `CULTURE_DIRECTED`, or `PROPHYLAXIS`. Because several guardrails converge on this single action, the cascade order matters and is fixed: after authentication, authorization, and existence checks, the server confirms the prescriber is active (`ERR_PRACTITIONER_INACTIVE`), then that the patient is still `ADMITTED` (`ERR_PATIENT_DISCHARGED`), then that the drug is formulary-active (`ERR_DRUG_SUSPENDED`). Only then do the clinical safety gates run: first the allergy block, then the renal guardrail. If the patient carries a penicillin allergy assessment in `SUSPECTED`, `TESTING_SCHEDULED`, `TESTED`, or `CONFIRMED` and the ordered drug has `is_penicillin_class` true, the order is rejected with `ERR_ALLERGY_BLOCKS_ORDER`; an assessment that reached `DELABELED` or `WITHDRAWN` no longer blocks. The renal guardrail rejects with `ERR_RENAL_DOSE_EXCEEDED` whenever the patient's `renal_function_crcl` is below 30 and the product of `dose_mg` and `frequency_per_day` exceeds 4000 mg per day. After safety comes referential integrity — patient, drug, and prescriber must share one hospital (`ERR_CROSS_FACILITY_REFERENCE`) — then the business constraints: a duplicate-active-order check rejects with `ERR_DUPLICATE_ACTIVE_ORDER` when the same patient already has an order for the same antimicrobial whose `therapy_status` is neither `COMPLETED` nor `DISCONTINUED`, and a per-patient cap rejects with `ERR_RESTRICTED_ORDER_CAP` when the patient already carries two concurrent restricted orders, where "concurrent" counts orders whose `approval_status` is `PENDING` or `APPROVED` and whose therapy has not reached a terminal state. Last among the ordering guards, a prescriber whose `stewardship_standing` has fallen to `SUSPENDED` may not place restricted-drug orders at all (`ERR_PRESCRIBER_SUSPENDED`).

What happens next depends on the drug. Ordering an unrestricted antimicrobial sets `approval_status` to `NOT_REQUIRED` and `therapy_status` to `ACTIVE`, and stamps `started_at` from the hospital clock. Either way, the four accrual counters — `administered_doses`, `cumulative_iv_hours`, `dot_calendar`, and `dot_dose` — start at zero, and `stopped_at` stays unset until the therapy closes. Ordering a restricted drug instead sets `approval_status` to `PENDING` and `therapy_status` to `AWAITING_APPROVAL`; the order sits inert — no doses may be recorded against it — until the approval workflow resolves.

That workflow begins when the prescriber (or an `IDPharmacist` acting on the case) submits an approval request carrying the `antibiotic_order_id`, the `requester_id`, and a `justification` of at least 20 characters; anything shorter fails with `ERR_INVALID_REQUEST`. Submission requires the target order's `approval_status` to be `PENDING` (`ERR_ORDER_APPROVAL_NOT_PENDING`), and the target order may have at most one open request at a time — a second submission while one stands in `SUBMITTED` or `ESCALATED` is rejected with `ERR_APPROVAL_ALREADY_OPEN`. A new request lands in `SUBMITTED` with `submitted_at` stamped from the clock, while `decided_at` and `decided_by_id` remain unset until a decision is recorded and `escalation_reason` stays empty unless the request is escalated.

Decisions belong to the committee: an `IDPharmacist` or the `StewardshipDirector` decides by supplying a `decision` of `APPROVED` or `DENIED` together with their `decider_id`. The guards run in a fixed sequence. The request must still be in `SUBMITTED` or `ESCALATED` (`ERR_APPROVAL_NOT_PENDING`); if it is `ESCALATED`, only the `StewardshipDirector` may proceed (`ERR_ESCALATED_REQUIRES_DIRECTOR`); the decider must differ from the `requester_id` (`ERR_SELF_APPROVAL_FORBIDDEN`); and the parent order's `approval_status` must still be `PENDING` (`ERR_ORDER_APPROVAL_NOT_PENDING`). Approval sets the order's `approval_status` to `APPROVED` and, when the order was waiting in `AWAITING_APPROVAL`, promotes `therapy_status` to `ACTIVE` with `started_at` stamped; the request records `decided_at` and `decided_by_id`. Denial sets the order's `approval_status` to `DENIED` and, when the order was waiting, moves `therapy_status` to `DISCONTINUED` with `stopped_at` stamped.

An `IDPharmacist` who wants director-level review escalates a `SUBMITTED` request by supplying an `escalation_reason` of at least 10 characters (a request no longer `SUBMITTED` fails with `ERR_APPROVAL_NOT_PENDING` before the reason is examined; shorter text then fails with `ERR_INVALID_REQUEST`). The reason is recorded and the request moves to `ESCALATED`. Escalated requests are exempt from auto-expiry. The requester themselves may retract a `SUBMITTED` request by withdrawing it: the supplied `withdrawer_id` must equal the `requester_id` (`ERR_NOT_REQUEST_OWNER`), and the request moves to `WITHDRAWN` while the order's `approval_status` reverts to `NOT_REQUIRED` and an `AWAITING_APPROVAL` order is moved to `DISCONTINUED` with `stopped_at` stamped. Finally, the clock sweep expires any `SUBMITTED` request once the clock reaches `submitted_at` plus the hospital's `restricted_auto_expire_hours`: the request becomes `EXPIRED`, the order's `approval_status` becomes `EXPIRED`, and a waiting order is discontinued with `stopped_at` stamped.

Once therapy is running, each administered dose is recorded by an `AttendingPhysician` or `IDPharmacist` with an `administered_at` timestamp. Recording a dose against a restricted drug whose `approval_status` is not `APPROVED` is rejected with `ERR_RESTRICTED_REQUIRES_APPROVAL`. Recording against an order whose therapy has closed (`COMPLETED` or `DISCONTINUED`) is rejected with `ERR_INVALID_REQUEST`, and the supplied `administered_at` is accepted as any valid ISO 8601 timestamp without comparison against the hospital clock. Each recording increments `administered_doses` by one; for an `IV` order it also adds a per-dose interval of twenty-four divided by `frequency_per_day` hours to `cumulative_iv_hours` (so a twice-daily IV drug accrues 12 hours per dose, a four-times-daily drug 6). The two DOT counters are then recomputed: `dot_calendar` counts the distinct UTC calendar dates on which at least one administration fell between `started_at` and the earlier of `stopped_at` or the relevant period end, while `dot_dose` is `administered_doses` divided by `frequency_per_day`, rounded half-up to two decimals. The recording response returns the fresh `administered_doses`, `cumulative_iv_hours`, `dot_calendar`, and `dot_dose`. When the calendar accrual reaches the hospital's `dot_review_threshold` — whether noticed at dose-recording time or by the next clock sweep — an order whose `approval_status` is `APPROVED` or `NOT_REQUIRED` is flagged from `ACTIVE` to `REVIEW_REQUIRED`, the threshold comparison being inclusive so that exactly the threshold length fires the flag.

Closing therapy has two shapes. Completing — an `AttendingPhysician` action available from `ACTIVE`, `REVIEW_REQUIRED`, `DEESCALATED`, or `CONVERTED` — requires that no intervention for the order stands in `RECOMMENDED` or `APPEALED` (`ERR_OPEN_INTERVENTION_BLOCKS_CLOSE`) and that the patient is still admitted (`ERR_PATIENT_DISCHARGED`); it moves the order to `COMPLETED`, stamps `stopped_at`, and triggers a final DOT recomputation. Discontinuing — available to `AttendingPhysician` and `IDPharmacist` from the same four states, subject again to the patient being admitted — moves the order to `DISCONTINUED`, stamps `stopped_at`, expires every conversion opportunity still in `DETECTED` for the order, and supersedes every intervention still in `DOCUMENTED` or `RECOMMENDED`. Either closing action invoked from any other therapy state is rejected with `ERR_INVALID_REQUEST`, and completion checks the patient's admission before the open-intervention guard. The approval-side cascades mirror this: when an `AWAITING_APPROVAL` order is denied, expired, or withdrawn out from under its request, the same cleanup of open interventions and opportunities applies, alongside the `stopped_at` stamping.

### 3.3. Prospective Audit and the Intervention Negotiation Cycle

Prospective audit is where the committee talks to the prescriber. An `IDPharmacist` documents an intervention against an order by supplying the `antibiotic_order_id`, their `auditor_id`, an `intervention_type` — one of `DOSE_OPTIMIZATION`, `DEESCALATION`, `IV_TO_PO`, `DURATION_REDUCTION`, or `STOP` — and a `recommendation_text` of at least 20 characters (`ERR_INVALID_REQUEST` below that). The record opens in `DOCUMENTED` with a placeholder `due_at` of the clock plus 24 hours, recomputed for real at issue time.

Issuing the recommendation requires the intervention to still be `DOCUMENTED` (`ERR_INTERVENTION_NOT_DRAFT`) and the target order's `therapy_status` to be `ACTIVE` or `REVIEW_REQUIRED` (`ERR_ORDER_NOT_AUDITABLE`). On issue, `recommendation_status` becomes `RECOMMENDED`, `due_at` is recomputed as the clock plus 24 hours, and an order that was `ACTIVE` is moved to `REVIEW_REQUIRED` so the chart visibly shows therapy under audit.

The prescriber responds with a `response` of `ACCEPTED` or `REJECTED` and their `responder_id`. The intervention must be `RECOMMENDED` (`ERR_INTERVENTION_NOT_PENDING`), the responder must be the order's own prescriber (`ERR_NOT_PRESCRIBER`), and the clock must not have passed `due_at` (`ERR_INTERVENTION_OVERDUE`). Either way the acting prescriber's id lands in `responded_by_id`. Acceptance drives the order according to the `intervention_type`: accepting a `STOP` recommendation closes therapy outright — the order moves from `REVIEW_REQUIRED` to `DISCONTINUED` with `stopped_at` stamped — while accepting any other type returns the order from `REVIEW_REQUIRED` toward resumed therapy, with two specializations: accepting an `IV_TO_PO` recommendation moves the order to `CONVERTED` and rewrites `route` to `PO`, and accepting a `DEESCALATION` recommendation moves the order to `DEESCALATED` and swaps its `antimicrobial_id` to the suggested replacement carried through the linked conversion opportunity — resolved as the `suggested_antimicrobial_id` of the most recently created `DEESCALATION` opportunity for the order (by `created_at`, then `id`), whatever that opportunity's status; when no such opportunity exists the drug is left unchanged while the order still moves to `DEESCALATED`. Rejection leaves the intervention in `REJECTED` and the order in `REVIEW_REQUIRED`, where it remains auditable.

A rejection is not necessarily the end. The auditor — and only the auditor, verified against `auditor_id` via the supplied `appealer_id` (`ERR_NOT_AUDIT_OWNER`) — may appeal an intervention standing in `REJECTED` (`ERR_INTERVENTION_NOT_APPEALABLE`), moving it to `APPEALED`. Adjudication belongs to the `StewardshipDirector`, who supplies a `verdict` and their `adjudicator_id`; the intervention must be `APPEALED` (`ERR_INTERVENTION_NOT_APPEALED`), and the adjudicator must be neither the auditor nor the original responder (`ERR_ADJUDICATOR_CONFLICT`). A verdict of `UPHOLD` stands the recommendation back up: the intervention returns to `RECOMMENDED` with a fresh `due_at` of the clock plus 24 hours, and the prescriber must respond again — the negotiation loop that gives this workflow its cyclic shape. A verdict of `OVERTURN` ends the matter in `REJECTED_FINAL`: the prescriber's `unresolved_noncompliance_count` increments by one and their standing is recomputed. In both outcomes the adjudicator's id is recorded in `appeal_adjudicator_id`.

Standing follows a simple ladder over the count of a prescriber's interventions resolved `REJECTED_FINAL`: three or more makes the prescriber `SUSPENDED`, exactly two puts them on `WATCH`, and anything less is `GOOD`. The operational teeth of `SUSPENDED` sit in §3.2's ordering gate. Two system-side transitions close interventions without touching standing: the clock sweep moves a `RECOMMENDED` intervention past its `due_at` to `SUPERSEDED` — non-response is deliberately not counted as noncompliance — and discontinuation of the parent order or discharge of the patient moves `DOCUMENTED` or `RECOMMENDED` interventions to `SUPERSEDED` as part of the cleanup cascades.

### 3.4. Microbiology Intake: Cultures, Susceptibility, and Culture-Driven Recommendation

The laboratory's side of the program begins when a `Microbiologist` registers a culture report with the `patient_case_id`, the `specimen_source` (an anatomic source such as `BLOOD`, `URINE`, `SPUTUM`, `WOUND`, or `CSF`), the `collected_at` timestamp, and the identified `organism` (for example `E_COLI`, `MRSA`, or `PSEUDOMONAS`). Collection may not lie in the future: `collected_at` after the hospital clock is rejected with `ERR_FUTURE_SPECIMEN`. A new report opens in `PRELIMINARY`, and at registration the server computes `is_first_isolate` — true when this is the patient's first isolate of that organism from that specimen source within the rolling 365-day window ending at `collected_at`, a flag on which all antibiogram counting later depends; the window is closed at both ends and counts prior reports of any status, so another report for the same patient, organism, and source collected exactly 365 days earlier or at the same instant makes the flag false. Finalizing the report moves it to `FINAL` and stamps `resulted_at` from the clock; finalizing carries no state guard, so re-finalizing a report simply re-stamps `resulted_at`. A report's `status` is drawn from `PRELIMINARY`, `FINAL`, and `AMENDED`; only `FINAL` and `AMENDED` reports may drive recommendations or feed antibiograms — a `PRELIMINARY` report is invisible to both.

Susceptibility rows are added to a culture by a `Microbiologist`, each naming the tested `antimicrobial_id`, an `interpretation` of `S` (susceptible), `I` (intermediate), or `R` (resistant) per the breakpoint standard, and a `mic_value` strictly greater than zero. The tested drug must belong to the same hospital as the culture's patient (`ERR_CROSS_FACILITY_REFERENCE`).

Once a culture is final, the culture-driven recommendation capability — open to `IDPharmacist`, `AttendingPhysician`, and `StewardshipDirector` — selects the narrowest adequate replacement for the patient's empiric therapy. Invoking it on a report that is not `FINAL` or `AMENDED` is not an error: the call returns HTTP 200 with `recommended_antimicrobial_id` null, `pool_size` zero, and `reason` `"culture_not_final"`. The candidate pool is built from this culture's susceptibility rows: the row's `interpretation` must be `S`, the drug's `formulary_status` must be `ACTIVE`, and the drug's class must be adequate for the specimen source — drugs whose `drug_class` is `MACROLIDE` are excluded when the `specimen_source` is `CSF`. Allergy posture then filters further: if the patient carries a penicillin allergy assessment in `SUSPECTED`, `TESTING_SCHEDULED`, `TESTED`, or `CONFIRMED`, any candidate whose `is_penicillin_class` is true is excluded; a `DELABELED` or `WITHDRAWN` assessment imposes no such exclusion. Ranking is deterministic: narrowest spectrum first by the class breadth ladder of §3.5; ties prefer a drug with `has_po_form` true; further ties go to the lower `mic_value`; and any remaining tie is broken by the drug's earlier `created_at` — never by identifier. When the pool is empty the call still succeeds with HTTP 200 and reports `recommended_antimicrobial_id` as null with a `pool_size` of zero and `reason` `"empty_pool"` — an empty pool is a reportable outcome, not an error. A non-empty result returns the chosen `recommended_antimicrobial_id` with the `pool_size` that produced it and `reason` `"selected"`.

### 3.5. Conversion and De-escalation Opportunity Detection

Opportunity detection is the program's proactive scanner: an `IDPharmacist` or `StewardshipDirector` asks the system to evaluate one candidate order by supplying the `antibiotic_order_id`, an `opportunity_kind` of `IV_TO_PO` or `DEESCALATION`, and — optional for `IV_TO_PO` but mandatory for `DEESCALATION`, where its absence fails with `ERR_INVALID_REQUEST` — a `suggested_antimicrobial_id` naming the suggested oral formulation (for `IV_TO_PO`) or the suggested narrower drug (for `DEESCALATION`). Each kind has its own hard gates and its own scoring rule, and a `ConversionOpportunity` is created in `DETECTED` — with `detected_at` stamped from the clock and `eligibility_score` computed per the kind — only when every gate passes and the score clears its floor; otherwise the detection is rejected with `ERR_CONVERSION_NOT_ELIGIBLE` or `ERR_DEESCALATION_NOT_ELIGIBLE` respectively.

For `IV_TO_PO`, five hard gates must all pass: the order's `route` is `IV`; the drug's `has_po_form` is true; the order's `cumulative_iv_hours` is at least the hospital's `iv_to_po_min_iv_hours` (the comparison is inclusive, so exactly the minimum qualifies); the patient's `has_enteral_access` is true; and either the patient's `is_immunocompromised` is false or, for an immunocompromised patient, the `cumulative_iv_hours` has reached twice the minimum. With all gates green, the score is the sum of three weighted terms, rounded half-up to two decimals. The hemodynamic stability term carries weight 1.0 and a fixed value of 40 points, the program-wide proxy for a stable patient. The renal term carries weight 0.4 and equals the patient's `renal_function_crcl` capped at 90 mL/min. The duration term carries weight 1.0 and starts from 30 points, decaying by 5 points for each full 24-hour block of IV time accrued beyond the hospital's minimum, and never drops below zero. An opportunity is created only when the final score is at least 60.

For `DEESCALATION`, four hard gates must pass: a `FINAL` culture report exists for the same patient; that culture carries a susceptibility row with `interpretation` `S` for the `suggested_antimicrobial_id`; the suggested drug's class is genuinely narrower than the current drug's class on the breadth ladder; and the order's `indication` is `EMPIRIC` or `CULTURE_DIRECTED`. The breadth ladder ranks `CARBAPENEM` at 90, `GLYCOPEPTIDE` at 70, `FLUOROQUINOLONE` at 60, `EXTENDED_SPECTRUM_PENICILLIN` at 50, `AMINOGLYCOSIDE` at 45, `CEPHALOSPORIN` at 40, `MACROLIDE` at 30, and `NARROW_PENICILLIN` at 20. A drug whose `drug_class` does not appear on the ladder is treated as breadth rank 999 — broader than every listed class — both in the recommendation ranking of §3.4 and in the narrowness gate here. The integer score then starts at a base of 50, adds 25 when the supporting culture's `is_first_isolate` is true, adds 15 when the order's `dot_calendar` has reached the hospital's `dot_review_threshold`, subtracts 20 when the patient `is_immunocompromised`, and adds ten times the breadth-rank difference between the current and suggested drugs. Because accepting a de-escalation could itself change the order's review posture, evaluation order is pinned: breadth ranks are read from the static ladder first, `dot_calendar` is snapshotted as of the clock second — before any side effect of this request — and the score is computed third, with no recomputation mid-request. A score of at least 65 creates the opportunity. When several `FINAL` cultures exist for the patient, the supporting culture is the newest by `resulted_at`, breaking ties by the later `collected_at` and then by `created_at`.

Actioning an opportunity belongs to the `AttendingPhysician`. Acceptance of an `IV_TO_PO` opportunity — the request carries the `accepter_id` — requires the opportunity to still be `DETECTED` (`ERR_OPPORTUNITY_NOT_DETECTED`), the order's `route` to be `IV` (`ERR_ORDER_NOT_IV`), and the drug's `has_po_form` to be true (`ERR_NO_ORAL_FORM`); on success the order's `route` becomes `PO`, its `therapy_status` becomes `CONVERTED`, the opportunity becomes `ACCEPTED`, and both DOT counters keep accruing under the new route. Acceptance of a `DEESCALATION` opportunity likewise requires `DETECTED`, plus a `FINAL` culture for the same patient carrying an `S` interpretation for the suggested drug (`ERR_NO_SUPPORTING_CULTURE`); on success the order's `antimicrobial_id` is rewritten to the `suggested_antimicrobial_id`, its `therapy_status` becomes `DEESCALATED`, and the opportunity becomes `ACCEPTED`. Declining — carrying the `decliner_id` — is likewise guarded: an opportunity no longer in `DETECTED` is rejected with `ERR_OPPORTUNITY_NOT_DETECTED`, and a live one moves to `DECLINED`. Opportunities left untouched expire: the clock sweep moves any `DETECTED` opportunity to `EXPIRED` once the clock stands more than 48 hours past `detected_at`.

### 3.6. Penicillin Allergy Delabeling

A labeled penicillin allergy follows most patients for life, and most labels are wrong; the delabeling workflow exists to test the low-risk ones. An `IDPharmacist` or `AttendingPhysician` opens an assessment with the `patient_case_id`, the free-text `reported_reaction` as recorded at intake, a `reaction_severity` of `MILD`, `MODERATE`, or `SEVERE`, and the `years_since_reaction` (zero or greater). At creation the server computes the `risk_score` and the `delabel_eligible` flag, and the assessment opens in `SUSPECTED`.

The risk score sums four terms and is capped and rounded at the end. The severity base contributes 10 points for `MILD`, 35 for `MODERATE`, and 80 for `SEVERE`. The reaction term adds 20 points when the `reported_reaction` text contains any of the anaphylaxis keywords — "anaphylaxis", "angioedema", "hives", or "wheeze" — matched case-insensitively as substrings, and adds nothing otherwise. The recency term starts at 30 points and decays by 3 points per elapsed year of `years_since_reaction`, never dropping below zero, so a reaction ten or more years old contributes nothing. The comorbidity term adds 10 points when the patient `is_immunocompromised`. The sum is capped at 100 and rounded half-up to two decimals. An assessment is `delabel_eligible` when its `risk_score` is below 30 and its `reaction_severity` is not `SEVERE`.

Scheduling a skin test or challenge is an `IDPharmacist` action from `SUSPECTED` and a `StewardshipDirector` action from `CONFIRMED` (a mismatched actor for the origin state is rejected with `ERR_INSUFFICIENT_PERMISSIONS`); any other non-terminal origin state is rejected with `ERR_ALLERGY_NOT_SCHEDULABLE`, while the terminal states `DELABELED` and `WITHDRAWN` are rejected with `ERR_ALLERGY_TERMINAL` before any origin check. Three guards then apply in order. A `SEVERE` assessment may never schedule a test, from any origin, and is rejected with `ERR_SEVERE_ALLERGY_BLOCKED`. From `SUSPECTED`, scheduling additionally requires `delabel_eligible` to be true — a `risk_score` of 30 or higher is rejected with `ERR_ALLERGY_HIGH_RISK`. From `CONFIRMED`, rechallenge requires the stored `years_since_reaction` to be at least 5 at scheduling time, else `ERR_RECHALLENGE_TOO_EARLY`. Scheduling moves the assessment to `TESTING_SCHEDULED` and recomputes the score on the verified baseline: the same formula, but with the recency term evaluated against the effective elapsed years — the stored `years_since_reaction` plus the full years elapsed between the assessment's `created_at` and the hospital clock at scheduling time — so an intake value that has aged yields a different score than the stored estimate.

Recording the outcome is an `IDPharmacist` action requiring the assessment to be `TESTING_SCHEDULED` (`ERR_ALLERGY_NOT_TESTING`); the supplied `test_result` must be one of `NEGATIVE`, `POSITIVE`, or `INDETERMINATE` (anything else, including the initial `NULL` placeholder the field carries before testing, fails with `ERR_INVALID_REQUEST`). The transition is automatic from there: `NEGATIVE` moves the assessment to `DELABELED` and the patient's penicillin allergy is considered removed, so order placements gated on the allergy no longer block; `POSITIVE` moves it to `CONFIRMED`; `INDETERMINATE` loops it back to `TESTING_SCHEDULED` for another attempt. An assessment may also be withdrawn by an `IDPharmacist` or the `StewardshipDirector` from `SUSPECTED`, `TESTING_SCHEDULED`, or `CONFIRMED`, moving it to `WITHDRAWN`; assessments already in the terminal states `DELABELED` or `WITHDRAWN` reject further transitions with `ERR_ALLERGY_TERMINAL`.

### 3.7. Antibiogram Production and Empiric Guideline Governance

Periodically the laboratory consolidates a surveillance window into an antibiogram. A `Microbiologist` creates one by naming the `hospital_id` and a `period_start` and `period_end`; the window is half-open — inclusive at the start, exclusive at the end — so adjacent periods share no isolate. An end not strictly after the start fails with `ERR_INVALID_PERIOD`, and a window overlapping an existing antibiogram window for the same hospital fails with `ERR_ANTIBIOGRAM_WINDOW_OVERLAP`; windows that merely touch at an endpoint are allowed. Rows are computed at creation, one per observed organism–drug pair, and the rounding order is pinned: each row's `pct_susceptible` is computed first, as one hundred times the row's `susceptible_count` divided by its `isolate_count`, rounded half-up to two decimals; only then is `is_reportable` evaluated as `isolate_count` reaching the hospital's `antibiogram_min_isolates`, and `row_count` tallied as the number of reportable rows. Pooling numerators and denominators across drugs and rounding once at the end yields different two-decimal values and is forbidden. The qualifying cultures for a row are reports of the hospital in `FINAL` or `AMENDED` status with `is_first_isolate` true whose `collected_at` falls within the half-open window and which carry a susceptibility row for that drug; `isolate_count` counts them and `susceptible_count` counts those interpreted `S`. If one culture carries several susceptibility rows for the same drug, that culture counts once toward the drug's `isolate_count` and toward `susceptible_count` when any of those rows is `S`. Row uniqueness is enforced per antibiogram, organism, and drug — a duplicate triple is rejected with `ERR_DUPLICATE_ROW`. The new antibiogram lands in `DRAFT` with `generated_at` stamped.

Publishing — available to `Microbiologist` and `StewardshipDirector` — requires the antibiogram to be `DRAFT` (`ERR_ANTIBIOGRAM_NOT_DRAFT`) and to carry at least one reportable row (`ERR_ANTIBIOGRAM_EMPTY`). Because publication re-baselines hospital-wide posture, it carries the optimistic-concurrency guard of §2.7: the request must include `expected_hospital_version` matching the hospital's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). Publication moves the antibiogram to `PUBLISHED`, moves any other `PUBLISHED` antibiogram of the same hospital to `SUPERSEDED` so that exactly one published posture exists at a time, increments the hospital's `version` by one, and sweeps every `ADOPTED` empiric guideline of the hospital for staleness: when the guideline's first-line drug now shows a `pct_susceptible` for its syndrome organism in this antibiogram that is 10 or more points below the value recorded at adoption, the guideline becomes `STALE`. The syndrome-mapped organism row is resolved deterministically: a row whose `organism` equals the guideline's `syndrome` string is preferred; failing that, if exactly one row exists for the drug it is used; otherwise the row with the lowest `pct_susceptible` is used, ties broken by earlier `created_at`. When no reportable row exists for the first-line drug in the new antibiogram, or the guideline has no recorded adoption percentage, the sweep leaves the guideline unchanged. A superseded antibiogram keeps its historical integrity — guidelines that referenced it keep their `source_antibiogram_id` pinned to it.

Guidelines translate antibiogram evidence into empiric policy. A `StewardshipDirector` or `IDPharmacist` drafts one by naming the `hospital_id`, the clinical `syndrome` (for example `CAP`, `HAP`, `UTI`, `SEPSIS`, or `SSTI`), the `first_line_antimicrobial_id` recommended for empiric therapy, the `source_antibiogram_id` this version derives from, and optionally a `supersedes_guideline_id` pointing at the previous guideline for the syndrome. The source antibiogram is required only to exist and belong to the same hospital at draft time; its `PUBLISHED` posture is enforced at adoption. The supersession reference, when given, must point at a guideline of the same hospital and same syndrome standing in `ADOPTED` or `STALE` — never at the draft itself — else `ERR_INVALID_SUPERSESSION`. A draft opens in `DRAFT`.

Adoption belongs to the `StewardshipDirector` alone and carries the same hospital-version guard as publication, since adopting mutates hospital-scoped posture and retires the incumbent: the request must carry `expected_hospital_version`, and a stale view is rejected with `ERR_STALE_VERSION` (HTTP 412). The remaining guards run in order: the guideline must be `DRAFT` (`ERR_GUIDELINE_NOT_DRAFT`); its source antibiogram must be `PUBLISHED` and of the same hospital (`ERR_ANTIBIOGRAM_NOT_PUBLISHED`); and the first-line drug's row for the syndrome-mapped organism in that antibiogram must be reportable with a `pct_susceptible` of at least 70 (`ERR_FIRST_LINE_BELOW_THRESHOLD`). Adoption moves the guideline to `ADOPTED`, records the `pct_susceptible_at_adoption` snapshot of the first-line drug, retires whichever guideline previously stood `ADOPTED` for the same hospital and syndrome, and increments the hospital's `version` by one.

Thereafter a guideline ages automatically. The staleness sweep at each subsequent publication can move an `ADOPTED` guideline to `STALE` as described above; the successor-adoption cascade moves an `ADOPTED` guideline to `RETIRED`. A `STALE` guideline does not block new therapy — instead, `EMPIRIC` orders created after staleness that reference the syndrome carry a non-blocking advisory note on their record, and no error is raised. Retirement by hand is a `StewardshipDirector` action available from exactly two postures, `DRAFT` and `STALE`; retiring from any other state (`ADOPTED` or `RETIRED`) is rejected with `ERR_GUIDELINE_NOT_RETIRABLE`.

### 3.8. Days-of-Therapy Metrics, Benchmarking, and Regulatory Submission

Measurement closes the loop. An `InfectionPreventionist` opens a monthly DOT snapshot by naming the `hospital_id`, a `period_label` in calendar-month form `YYYY-MM` (a malformed label is rejected with `ERR_INVALID_REQUEST`) that is unique within the hospital (a repeat is rejected with `ERR_DUPLICATE_SNAPSHOT_PERIOD`), and the `patient_days` denominator — the inpatient days present that month, strictly greater than zero. The snapshot opens in `OPEN` with all derived metrics computed. While a snapshot is `OPEN`, single-resource reads recompute its derived metrics live against current data; finalization freezes them, and reads of a `FINALIZED` snapshot return the frozen values.

Days of therapy are counted in two bases, and the program keeps both because they answer different questions. Under the calendar basis, any calendar UTC date on which at least one dose was administered contributes one DOT regardless of how many doses fell that day: two same-day doses during a three-day course contribute 3 DOT. Under the dose basis, accrual is normalized by regimen: each order's `dot_dose` is its `administered_doses` divided by `frequency_per_day`, rounded half-up to two decimals, so those same two same-day doses during a three-day twice-daily course contribute 3.00 — while a four-times-daily regimen would yield 1.50 for the same events. A calendar date belongs to the month containing its UTC date, and each snapshot aggregates the slices attributable to its month: `total_dot_calendar` sums the per-order calendar counts and `total_dot_dose` sums the per-order dose counts (two decimals, round half up). The input set is every order of the hospital whose `therapy_status` is `ACTIVE`, `REVIEW_REQUIRED`, `DEESCALATED`, `CONVERTED`, `COMPLETED`, or `DISCONTINUED` and whose therapy window — `started_at` through `stopped_at`, or through the hospital clock when the order has not stopped — intersects the snapshot month; orders still in `AWAITING_APPROVAL` are excluded because no doses can have been recorded against them. From the totals, `dot_per_1000_pd_calendar` is one thousand times `total_dot_calendar` divided by `patient_days`, and `dot_per_1000_pd_dose` is one thousand times `total_dot_dose` divided by `patient_days`, both rounded half-up to two decimals.

Benchmarking converts the calendar-basis rate into a standing against the standard reference table. The percentile is the largest named percentile whose floor the hospital's `dot_per_1000_pd_calendar` meets or exceeds: the floors are 0 for the 10th, 350 for the 25th, 480 for the 50th, 620 for the 75th, and 780 for the 90th, and they are inclusive — a rate of exactly 780 reports a `benchmark_percentile` of 90, a rate of 779.99 reports 75, and any rate below 350 reports 10.

Finalizing a snapshot — open to `InfectionPreventionist` and `StewardshipDirector` — requires the snapshot to be `OPEN` (`ERR_SNAPSHOT_NOT_OPEN`) and the `period_label` month to lie strictly before the month of the hospital clock (`ERR_PERIOD_NOT_CLOSED`); finalization recomputes all DOT totals one last time, freezes them, and moves the snapshot to `FINALIZED`. A finalized snapshot may be reopened only by the `StewardshipDirector` and only while no regulatory report in `SUBMITTED` or `ACCEPTED` pins it: reopening a snapshot that is not `FINALIZED` fails with `ERR_SNAPSHOT_NOT_FINALIZED`, and reopening one pinned by such a report fails with `ERR_SNAPSHOT_PINNED_BY_REPORT`.

Regulatory submission is the program's outward face. An `InfectionPreventionist` drafts a report with the `hospital_id`, a `report_type` of `NHSN_AUR` or `STATE_MANDATE`, the covered `period_label`, and the `dot_snapshot_id` to pin; the pinned snapshot must be `FINALIZED`, belong to the same hospital, and carry a matching `period_label` (`ERR_SNAPSHOT_NOT_FINAL`). Submission — again the preventionist's action — requires the report to be `DRAFT` (`ERR_REPORT_NOT_DRAFT`), re-verifies the pinned snapshot's finalized posture, and refuses to proceed when another report for the same hospital, report type, and period already stands in `SUBMITTED` or `ACCEPTED` (`ERR_REPORT_ALREADY_SUBMITTED`). At submission the server assembles `payload_json` as canonical JSON — keys sorted, no whitespace — containing exactly the facility identifier `nhsn_facility_id`, the `report_type`, the `period_label`, both per-thousand rates, both DOT totals, the `patient_days`, and the `benchmark_percentile`, every value taken from the pinned snapshot at that instant; per-thousand values serialize with exactly two decimal places, `total_dot_calendar` serializes as an integer, and `total_dot_dose` serializes as an integer when its value is integral and with exactly two decimal places otherwise. The `checksum` is the FNV-1a 32-bit hash of `payload_json` rendered as eight lowercase hexadecimal characters, serving as tamper evidence, and determinism is guaranteed: the same snapshot with the same report header yields a byte-identical payload. Later recomputation of the snapshot after a reopen must not mutate an already-submitted payload. Submission stamps `submitted_at` and moves the report to `SUBMITTED`.

The regulator's answer is recorded by the `StewardshipDirector` through an acknowledgement carrying an `ack` of `ACCEPTED` or `REJECTED`; only a `SUBMITTED` report may be acknowledged (`ERR_REPORT_NOT_SUBMITTED`). Acceptance is terminal. Rejection is not the end of the month: the correction path is to draft a new report referencing the same pinned snapshot and submit again, while the prior `REJECTED` report is retained for audit.

## 4. Endpoint Definitions

Operations that create new resources — hospitals, practitioners, patient cases, formulary drugs, allergy assessments, culture reports, susceptibility rows, antibiotic orders, administration records, approval requests, audit interventions, conversion-opportunity detections, antibiograms, empiric guidelines, DOT snapshots, and regulatory reports — return `201 Created`. Operations that act on an existing resource without creating a new one — decisions, escalations, withdrawals, issues, responses, appeals, adjudications, accepts, declines, publications, adoptions, retirements, finalizations, reopens, submissions, acknowledgements, discharges, completions, discontinuations, clock advances, and patches — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/stewardship/_clock/set_current_utc` | Advance the hospital logical clock and run the scheduled sweeps | StewardshipDirector, StewardshipAdmin |
| POST | `/stewardship/hospitals` | Create a hospital (stewardship program scope) | StewardshipAdmin |
| GET | `/stewardship/hospitals/{id}` | Get a hospital | All roles |
| GET | `/stewardship/hospitals` | List hospitals | All roles |
| POST | `/stewardship/practitioners` | Register a practitioner | StewardshipAdmin |
| GET | `/stewardship/practitioners/{id}` | Get a practitioner | All roles |
| GET | `/stewardship/practitioners` | List practitioners, filterable by `hospital_id` and `discipline` | All roles |
| PATCH | `/stewardship/practitioners/{id}` | Update practitioner deactivation or committee membership | StewardshipAdmin |
| POST | `/stewardship/patient-cases` | Admit a patient case | AttendingPhysician, IDPharmacist, StewardshipAdmin |
| GET | `/stewardship/patient-cases/{id}` | Get a patient case | All roles |
| GET | `/stewardship/patient-cases` | List patient cases, filterable by `hospital_id` and `status` | All roles |
| POST | `/stewardship/patient-cases/{id}/discharge` | Discharge a patient, locking open orders and interventions | AttendingPhysician |
| POST | `/stewardship/antimicrobials` | Add a drug to the formulary | StewardshipAdmin, IDPharmacist |
| GET | `/stewardship/antimicrobials/{id}` | Get a formulary drug | All roles |
| GET | `/stewardship/antimicrobials` | List the formulary, filterable by `hospital_id`, `is_restricted`, and `drug_class` | All roles |
| PATCH | `/stewardship/antimicrobials/{id}` | Update formulary status (suspend or reactivate) | StewardshipAdmin, IDPharmacist |
| POST | `/stewardship/allergy-assessments` | Open a penicillin allergy assessment | IDPharmacist, AttendingPhysician |
| GET | `/stewardship/allergy-assessments/{id}` | Get an allergy assessment | All roles |
| GET | `/stewardship/allergy-assessments` | List allergy assessments, filterable by `patient_case_id` and `status` | All roles |
| POST | `/stewardship/allergy-assessments/{id}/schedule-test` | Schedule a penicillin skin test or challenge | IDPharmacist, StewardshipDirector |
| POST | `/stewardship/allergy-assessments/{id}/record-result` | Record the test outcome, auto-transitioning the assessment | IDPharmacist |
| POST | `/stewardship/allergy-assessments/{id}/withdraw` | Withdraw an assessment | IDPharmacist, StewardshipDirector |
| POST | `/stewardship/culture-reports` | Register a culture report (starts preliminary) | Microbiologist |
| GET | `/stewardship/culture-reports/{id}` | Get a culture report | All roles |
| GET | `/stewardship/culture-reports` | List culture reports, filterable by `patient_case_id`, `status`, and `organism` | All roles |
| POST | `/stewardship/culture-reports/{id}/finalize` | Finalize a culture report | Microbiologist |
| POST | `/stewardship/culture-reports/{id}/susceptibility-results` | Add a susceptibility row to a culture | Microbiologist |
| GET | `/stewardship/culture-reports/{id}/susceptibility-results` | List susceptibility rows of a culture | All roles |
| GET | `/stewardship/susceptibility-results` | List susceptibility results across cultures, filterable by `culture_report_id`, `antimicrobial_id`, and `interpretation` | All roles |
| GET | `/stewardship/susceptibility-results/{id}` | Get a single susceptibility result | All roles |
| POST | `/stewardship/culture-reports/{id}/recommend` | Run the culture-driven recommendation selector | IDPharmacist, AttendingPhysician, StewardshipDirector |
| POST | `/stewardship/antibiotic-orders` | Place an antibiotic order | AttendingPhysician |
| GET | `/stewardship/antibiotic-orders/{id}` | Get an order | All roles |
| GET | `/stewardship/antibiotic-orders` | List orders, filterable by `patient_case_id`, `antimicrobial_id`, `prescriber_id`, `therapy_status`, and `approval_status` | All roles |
| POST | `/stewardship/antibiotic-orders/{id}/administrations` | Record an administered dose, advancing DOT and IV-hour counters | AttendingPhysician, IDPharmacist |
| POST | `/stewardship/antibiotic-orders/{id}/complete` | Complete therapy | AttendingPhysician |
| POST | `/stewardship/antibiotic-orders/{id}/discontinue` | Discontinue therapy | AttendingPhysician, IDPharmacist |
| POST | `/stewardship/approval-requests` | Submit a restricted-drug approval request | AttendingPhysician, IDPharmacist |
| GET | `/stewardship/approval-requests/{id}` | Get an approval request | All roles |
| GET | `/stewardship/approval-requests` | List approval requests, filterable by `antibiotic_order_id`, `requester_id`, `decided_by_id`, and `status` | All roles |
| POST | `/stewardship/approval-requests/{id}/decide` | Decide an approval request | IDPharmacist, StewardshipDirector |
| POST | `/stewardship/approval-requests/{id}/escalate` | Escalate a request to the StewardshipDirector | IDPharmacist |
| POST | `/stewardship/approval-requests/{id}/withdraw` | Withdraw an approval request (requester only) | AttendingPhysician, IDPharmacist |
| POST | `/stewardship/audit-interventions` | Document a prospective audit intervention | IDPharmacist |
| GET | `/stewardship/audit-interventions/{id}` | Get an intervention | All roles |
| GET | `/stewardship/audit-interventions` | List interventions, filterable by `antibiotic_order_id`, `auditor_id`, `responded_by_id`, `appeal_adjudicator_id`, and `recommendation_status` | All roles |
| POST | `/stewardship/audit-interventions/{id}/issue` | Issue the recommendation to the prescriber | IDPharmacist |
| POST | `/stewardship/audit-interventions/{id}/respond` | Prescriber responds accepted or rejected | AttendingPhysician |
| POST | `/stewardship/audit-interventions/{id}/appeal` | Auditor appeals a rejection | IDPharmacist |
| POST | `/stewardship/audit-interventions/{id}/adjudicate` | Committee adjudicates an appeal (uphold loops; overturn is final) | StewardshipDirector |
| POST | `/stewardship/conversion-opportunities/detect` | Run opportunity detection for a candidate order | IDPharmacist, StewardshipDirector |
| GET | `/stewardship/conversion-opportunities/{id}` | Get an opportunity | All roles |
| GET | `/stewardship/conversion-opportunities` | List opportunities, filterable by `antibiotic_order_id`, `opportunity_kind`, `suggested_antimicrobial_id`, and `status` | All roles |
| POST | `/stewardship/conversion-opportunities/{id}/accept` | Accept an opportunity, applying the route or drug change | AttendingPhysician |
| POST | `/stewardship/conversion-opportunities/{id}/decline` | Decline an opportunity | AttendingPhysician |
| POST | `/stewardship/antibiograms` | Create an antibiogram for a period (rows computed at creation) | Microbiologist |
| GET | `/stewardship/antibiograms/{id}` | Get an antibiogram | All roles |
| GET | `/stewardship/antibiograms` | List antibiograms, filterable by `hospital_id` and `status` | All roles |
| GET | `/stewardship/antibiograms/{id}/rows` | List an antibiogram's rows | All roles |
| GET | `/stewardship/antibiogram-rows` | List antibiogram rows across antibiograms, filterable by `antibiogram_id`, `antimicrobial_id`, and `organism` | All roles |
| GET | `/stewardship/antibiogram-rows/{id}` | Get a single antibiogram row | All roles |
| POST | `/stewardship/antibiograms/{id}/publish` | Publish an antibiogram (supersedes prior; re-evaluates guideline staleness; OCC on hospital version) | Microbiologist, StewardshipDirector |
| POST | `/stewardship/empiric-guidelines` | Draft an empiric guideline referencing a published antibiogram | StewardshipDirector, IDPharmacist |
| GET | `/stewardship/empiric-guidelines/{id}` | Get a guideline | All roles |
| GET | `/stewardship/empiric-guidelines` | List guidelines, filterable by `hospital_id`, `syndrome`, `status`, `first_line_antimicrobial_id`, `source_antibiogram_id`, and `supersedes_guideline_id` | All roles |
| POST | `/stewardship/empiric-guidelines/{id}/adopt` | Adopt a guideline, retiring the prior adopted one for the syndrome (OCC on hospital version) | StewardshipDirector |
| POST | `/stewardship/empiric-guidelines/{id}/retire` | Retire a draft or stale guideline | StewardshipDirector |
| POST | `/stewardship/dot-snapshots` | Open a monthly DOT metric snapshot (totals computed) | InfectionPreventionist |
| GET | `/stewardship/dot-snapshots/{id}` | Get a snapshot | All roles |
| GET | `/stewardship/dot-snapshots` | List snapshots, filterable by `hospital_id`, `period_label`, and `status` | All roles |
| POST | `/stewardship/dot-snapshots/{id}/finalize` | Finalize a snapshot (period must be closed) | InfectionPreventionist, StewardshipDirector |
| POST | `/stewardship/dot-snapshots/{id}/reopen` | Reopen a finalized snapshot (blocked when pinned by a submitted report) | StewardshipDirector |
| POST | `/stewardship/regulatory-reports` | Draft a regulatory report pinning a snapshot | InfectionPreventionist |
| GET | `/stewardship/regulatory-reports/{id}` | Get a report | All roles |
| GET | `/stewardship/regulatory-reports` | List reports, filterable by `hospital_id`, `report_type`, `dot_snapshot_id`, and `status` | All roles |
| POST | `/stewardship/regulatory-reports/{id}/submit` | Submit a report, assembling the payload and checksum from the pinned snapshot | InfectionPreventionist |
| POST | `/stewardship/regulatory-reports/{id}/acknowledge` | Record regulator acknowledgement (accepted or rejected) | StewardshipDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PERIOD` | 422 Unprocessable Entity |
| `ERR_INVALID_SUPERSESSION` | 422 Unprocessable Entity |
| `ERR_PRACTITIONER_INACTIVE` | 409 Conflict |
| `ERR_PATIENT_DISCHARGED` | 409 Conflict |
| `ERR_DRUG_SUSPENDED` | 409 Conflict |
| `ERR_ORDER_NOT_AUDITABLE` | 409 Conflict |
| `ERR_ORDER_NOT_IV` | 409 Conflict |
| `ERR_NO_ORAL_FORM` | 409 Conflict |
| `ERR_ORDER_APPROVAL_NOT_PENDING` | 409 Conflict |
| `ERR_APPROVAL_NOT_PENDING` | 409 Conflict |
| `ERR_ESCALATED_REQUIRES_DIRECTOR` | 403 Forbidden |
| `ERR_INTERVENTION_NOT_DRAFT` | 409 Conflict |
| `ERR_INTERVENTION_NOT_PENDING` | 409 Conflict |
| `ERR_INTERVENTION_NOT_APPEALABLE` | 409 Conflict |
| `ERR_INTERVENTION_NOT_APPEALED` | 409 Conflict |
| `ERR_OPPORTUNITY_NOT_DETECTED` | 409 Conflict |
| `ERR_ALLERGY_NOT_SCHEDULABLE` | 409 Conflict |
| `ERR_ALLERGY_NOT_TESTING` | 409 Conflict |
| `ERR_ALLERGY_TERMINAL` | 409 Conflict |
| `ERR_ANTIBIOGRAM_NOT_DRAFT` | 409 Conflict |
| `ERR_ANTIBIOGRAM_EMPTY` | 409 Conflict |
| `ERR_ANTIBIOGRAM_NOT_PUBLISHED` | 409 Conflict |
| `ERR_GUIDELINE_NOT_DRAFT` | 409 Conflict |
| `ERR_GUIDELINE_NOT_STALE` | 409 Conflict |
| `ERR_GUIDELINE_NOT_RETIRABLE` | 409 Conflict |
| `ERR_SNAPSHOT_NOT_OPEN` | 409 Conflict |
| `ERR_SNAPSHOT_NOT_FINALIZED` | 409 Conflict |
| `ERR_SNAPSHOT_PINNED_BY_REPORT` | 409 Conflict |
| `ERR_SNAPSHOT_NOT_FINAL` | 409 Conflict |
| `ERR_REPORT_NOT_DRAFT` | 409 Conflict |
| `ERR_REPORT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_ALLERGY_BLOCKS_ORDER` | 422 Unprocessable Entity |
| `ERR_RENAL_DOSE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SEVERE_ALLERGY_BLOCKED` | 422 Unprocessable Entity |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_ADJUDICATOR_CONFLICT` | 422 Unprocessable Entity |
| `ERR_FUTURE_SPECIMEN` | 422 Unprocessable Entity |
| `ERR_INTERVENTION_OVERDUE` | 422 Unprocessable Entity |
| `ERR_ANTIBIOGRAM_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_RECHALLENGE_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_PERIOD_NOT_CLOSED` | 422 Unprocessable Entity |
| `ERR_CLOCK_REGRESSION` | 422 Unprocessable Entity |
| `ERR_CROSS_FACILITY_REFERENCE` | 422 Unprocessable Entity |
| `ERR_NO_SUPPORTING_CULTURE` | 422 Unprocessable Entity |
| `ERR_RESTRICTED_REQUIRES_APPROVAL` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE_ORDER` | 409 Conflict |
| `ERR_RESTRICTED_ORDER_CAP` | 409 Conflict |
| `ERR_DUPLICATE_ROW` | 409 Conflict |
| `ERR_APPROVAL_ALREADY_OPEN` | 409 Conflict |
| `ERR_DUPLICATE_SNAPSHOT_PERIOD` | 409 Conflict |
| `ERR_REPORT_ALREADY_SUBMITTED` | 409 Conflict |
| `ERR_NOT_REQUEST_OWNER` | 403 Forbidden |
| `ERR_NOT_PRESCRIBER` | 403 Forbidden |
| `ERR_NOT_AUDIT_OWNER` | 403 Forbidden |
| `ERR_OPEN_INTERVENTION_BLOCKS_CLOSE` | 409 Conflict |
| `ERR_FIRST_LINE_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_PRESCRIBER_SUSPENDED` | 403 Forbidden |
| `ERR_CONVERSION_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_DEESCALATION_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_ALLERGY_HIGH_RISK` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
