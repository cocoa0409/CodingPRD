# Non-Revenue Water Loss Reduction API — Product Requirements Document

## 1. Introduction

Water utilities lose a substantial share of treated, pressurized water between the treatment plant and the customer's tap — through leaking mains, inaccurate customer meters, and outright unauthorized consumption. This lost volume, known as **non-revenue water** (NRW), represents both forgone revenue and wasted treatment energy, and state regulators increasingly require utilities to quantify it, explain it, and demonstrate a credible program for driving it down. This document specifies the Non-Revenue Water Loss Reduction API, the system of record for a utility's loss-reduction program: it organizes the service territory into **District Metered Areas** (DMAs), maintains an audited water balance for each DMA, monitors minimum night flows, runs leak detection surveys and repair campaigns, administers the customer meter accuracy and replacement program, investigates unauthorized consumption, plans pressure management interventions, evaluates the economics of each candidate intervention, and compiles the annual benchmark report submitted to the state.

The API is built around three operating principles. First, **segregation of duties**: the analyst who drafts a water balance may not finalize it, the supervisor who reports a leak may not verify its repair, and the investigator who substantiates an unauthorized-consumption case may not approve its billing adjustment. Second, **posture-driven gating**: each DMA carries a derived posture that tightens automatically while a balance is under review, a pressure project is in the field, or a benchmark report covering the DMA is before the regulator, and that posture gates which child operations may proceed. Third, **auditability**: every mutating operation appends an audit event, and every computed figure — NRW percentage, Infrastructure Leakage Index, repair priority score, benefit–cost ratio — is reproducible from stated rules with stated constants.

All resources are mounted under the `/nrw` prefix. A server-maintained logical clock, rather than wall-clock time, governs every time-dependent rule in the system, so that age-based and scheduling behaviors are deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the capacity in which they act. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not on the endpoint's authorized-role list is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly six roles. `ProgramDirector` is the utility program director: it administers DMAs, approves and rejects pressure projects and intervention proposals, activates and commissions pressure projects, approves or rejects billing adjustments on unauthorized-consumption cases, and is the only role permitted to set the logical clock. `UtilityAnalyst` is the NRW analyst: it owns water balance periods, night-flow assessments, pressure project drafting, and intervention proposal drafting and submission. `FieldSupervisor` is the leak-detection crew lead: it plans and runs leak surveys and drives the entire leak lifecycle from report through verified repair. `MeterTechnician` is the meter shop technician: it registers customer meters, schedules and completes accuracy tests, and executes flags, replacements, and retirements. `Investigator` is the revenue-protection investigator: it owns unauthorized-consumption cases end to end, from opening through evidence gathering, substantiation, adjustment proposal, and posting. `RegulatorLiaison` is the state reporting liaison: it creates, submits, accepts, and returns benchmark reports.

For every role, `X-User-ID` is an **opaque operator identifier not tied to any persisted entity**. The server records it where a workflow requires an accountability anchor — for example `created_by_user_id` on a water balance period, `reported_by_user_id` on a leak, `crew_lead_user_id` on a leak survey, `substantiated_by_user_id` on an unauthorized-consumption case, and `actor_user_id` on audit events — and the segregation-of-duties rules in §2.11 compare it against those anchors, but the server never compares `X-User-ID` against any entity's `id`. This holds identically for `ProgramDirector`, `UtilityAnalyst`, `FieldSupervisor`, `MeterTechnician`, `Investigator`, and `RegulatorLiaison`.

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

Requests that match no defined path, and requests that use an unsupported method on a defined path, are rejected with `ERR_NOT_FOUND` (HTTP 404) in the standard error envelope.

---

### 2.3. Pagination

List endpoints paginate through two query parameters. `limit` caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and accepts a maximum of 100. `offset` states how many items to skip and defaults to 0. A `limit` that is not an integer, is below 1, or is above 100, and an `offset` that is not an integer or is below 0, are rejected with `ERR_VALIDATION` (HTTP 422). Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`. Unless otherwise noted, a filter query parameter matches by exact equality against the named field.

### 2.4. Common Resource Properties

Every primary resource — DMA, water balance period, night-flow assessment, leak survey, leak, customer meter, meter accuracy test, unauthorized-consumption case, pressure project, intervention proposal, and benchmark report — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the most recent modification; it refreshes on every change to the resource, including recomputation of derived fields stored on that resource.
- `version` (integer): a system-managed integer that starts at 1 at creation and increments by one on every modification of the resource, including modifications caused by derived-field recomputation on that resource.

The audit event is the single exception: because it is an immutable, append-only record, it carries only `id` and `created_at`; both `updated_at` and `version` are absent.

### 2.5. The Logical Clock

The server maintains a logical clock that governs every time-dependent rule in the system: survey start gating, pressure project activation gating, meter age computation, and the installation timestamp stamped on replacement meters. Before any client call has set it, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `ProgramDirector` may advance the clock through an administrative capability that accepts a target instant `to_iso8601` — any parseable ISO 8601 instant is accepted, including one earlier than the current reading — and returns `200 OK` with the resulting `current_utc` in the data field. Setting the clock appends no audit event of its own; only the meter transitions it triggers are audited. Advancing the clock re-evaluates the age lane of the meter replacement policy (§3.5): the `replacement_due` flag is recomputed for every meter whose `replacement_policy` is `AGE_BASED` or `HYBRID`, and any `IN_SERVICE` meter whose age crosses the program's fifteen-year limit transitions to `FLAGGED_FOR_REPLACEMENT`, with an audit event appended.

### 2.6. District Posture: The Derived Gating State

Every DMA carries a derived field `posture` with three values — `OPEN`, `RESTRICTED`, and `FROZEN` — that summarizes what is currently happening beneath it. No endpoint sets `posture` directly; the server recomputes it on every relevant child mutation, and every recompute that changes the value increments the DMA's `version` by one and refreshes its `updated_at`. A DMA begins life `OPEN`. It becomes `RESTRICTED` the moment any child water balance period enters `SUBMITTED` or any child pressure project enters `ACTIVE`, and it returns from `RESTRICTED` to `OPEN` when no child balance period remains in `SUBMITTED` and no child pressure project remains `ACTIVE`. It becomes `FROZEN` when a benchmark report whose `dma_ids` contains that DMA enters `SUBMITTED` or `ACCEPTED`, and it returns from `FROZEN` to `OPEN` only when the covering report enters `RETURNED` and no other gating child state holds (no balance period in `SUBMITTED`, no pressure project `ACTIVE`). Acceptance of a benchmark report therefore does not release the freeze; only a return does. When a freeze condition and a restriction condition hold simultaneously, the posture is `FROZEN`; when the freeze releases while a gating child state still holds (a balance period in `SUBMITTED` or a pressure project `ACTIVE`), the DMA becomes `RESTRICTED` rather than `OPEN`.

Posture gates child operations. While a DMA is `FROZEN`, the following eight operations are rejected with `ERR_DMA_FROZEN` (HTTP 409): creating a water balance period for the DMA, submitting a water balance period, finalizing a water balance period, creating a leak survey in the DMA, starting field work on a leak survey, approving a pressure project, creating an intervention proposal for the DMA, and submitting an intervention proposal. One of these is stricter: approving a pressure project requires the DMA's posture to be exactly `OPEN` — a `RESTRICTED` posture, not merely a `FROZEN` one, already blocks approval — while the other seven tolerate `RESTRICTED`. Starting a leak survey likewise requires posture `OPEN`, as stated by its own preconditions in §3.3.

### 2.7. Order of Validation

When several checks could fail on the same request, the server evaluates them in a fixed priority order and reports only the first failure encountered. The order is:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is recognized; failure yields `ERR_UNAUTHENTICATED` (HTTP 401). Applies to every endpoint.
2. **Authorization** — the acting role appears in the endpoint's authorized-role list; failure yields `ERR_UNAUTHORIZED` (HTTP 403). Applies to every endpoint.
3. **Existence** — every identifier in the path, and every foreign key in the request body (`dma_id`, `survey_id`, `meter_id`, and every element of `dma_ids`), resolves to an existing row; failure yields `ERR_NOT_FOUND` (HTTP 404).
4. **Uniqueness** — the DMA `code` and the customer meter `serial_number` (including the replacement serial supplied at replacement time) are unique across the utility; failure yields `ERR_DUPLICATE` (HTTP 409). This check applies to DMA creation, meter registration, and meter replacement.
5. **State-machine validity** — the target entity is in a from-state that permits the invoked transition, and terminal states reject every transition; failure yields `ERR_INVALID_STATE` (HTTP 409). Applies to all action endpoints.
6. **DMA posture gate** — the operations enumerated in §2.6 require the parent DMA's posture to be non-`FROZEN` (and pressure-project approval requires exactly `OPEN`); failure yields `ERR_DMA_FROZEN` (HTTP 409).
7. **Segregation of duties** — the acting user differs from the anchor user on the three segregated transitions described in §2.11; failure yields `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
8. **Interval arithmetic** — period, window, and planned-interval ordering, duration bounds, and non-overlap rules described in §3.2, §3.3, and §3.7; failure yields `ERR_WINDOW_CONFLICT` (HTTP 409). This check applies when creating a water balance period, a night-flow assessment, a leak survey, or a pressure project.
9. **Scalar constraints** — numeric ranges, enum membership, required-field presence, and cross-field orderings on individual fields; failure yields `ERR_VALIDATION` (HTTP 422). Applies to every create and action endpoint that carries a body.
10. **Cross-entity prerequisites** — content prerequisites that span entities: a qualifying finalized balance for benchmark submission, an `estimated_loss_m3` for substantiation, an `actual_repair_cost` for repair completion, and a `measured_pressure_m` for commissioning; failure yields `ERR_MISSING_PREREQUISITE` (HTTP 422). An explicit JSON null for one of these prerequisite fields is treated as omitted.
11. **Benefit–cost approval gate** — an intervention proposal may be approved only when its benefit–cost ratio meets the program threshold; failure yields `ERR_BCR_BELOW_THRESHOLD` (HTTP 422).
12. **Water-balance consistency** — a water balance may be submitted only when its inputs reconcile to a non-negative real-loss remainder; failure yields `ERR_BALANCE_INCONSISTENT` (HTTP 422).
13. **Optimistic concurrency** — the `expected_dma_version` or `expected_report_version` carried by the two OCC-guarded writes in §2.10 matches the parent's current `version`; failure yields `ERR_STALE_VERSION` (HTTP 412).
14. **Cancellation children guard** — a leak survey may be cancelled only when its child leaks satisfy the state guard of §3.3; failure yields `ERR_CHILDREN_OPEN` (HTTP 409).

### 2.8. Nested Resource Retrieval and Referential Integrity

Requests that target nested resources validate path identifiers sequentially from left to right, rejecting with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing row. The same existence duty extends to foreign keys supplied in request bodies: a `dma_id` on a child creation, a `survey_id` on a leak report, a `meter_id` on an accuracy test, and every element of a benchmark report's `dma_ids` array must each resolve to an existing row, and any that does not is rejected with `ERR_NOT_FOUND`. A scalar body foreign key (`dma_id`, `survey_id`, `meter_id`) whose value is not a string at all fails scalar validation with `ERR_VALIDATION` (HTTP 422) instead; a non-string element of a benchmark report's `dma_ids` array is rejected with `ERR_NOT_FOUND`, like an unresolvable identifier. Existence is always established before any state, posture, or business rule is evaluated, per the ordering in §2.7.

### 2.9. Numeric Precision, Rounding, and Units

All computed percentages, scores, ratios, and indices stored on resources are rounded **half-up to 2 decimal places** unless a specific rule states otherwise. The exceptions are: litre-per-second flow figures (`measured_mnf_lps`, `expected_legitimate_night_use_lps`, `net_night_flow_lps`, `estimated_loss_lps`, `flow_rate_lps`), which are kept at input precision; the pressure-management leak-reduction volume estimate, which is rounded half-up to a whole cubic metre (0 decimal places); the intervention `payback_years`, which is rounded half-up to 1 decimal place; and the present-value factor inside the benefit–cost calculation, which is itself rounded half-up to 6 decimal places before being used. Input volumes in cubic metres and monetary amounts are stored at input precision. All arithmetic uses decimal semantics so that reported figures are exactly reproducible from the rules in §3.

### 2.10. Optimistic Concurrency Control

Exactly two write operations carry an optimistic-concurrency guard, and each names its guard field explicitly.

Creating a water balance period requires the request to carry `expected_dma_version`, a non-optional field holding the `version` of the parent DMA as the client last observed it. If the DMA's current `version` has advanced since that observation — for instance because another writer submitted a balance for an overlapping window, which legitimately recomputed the DMA's posture — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from building a balance on a stale posture or connection-count snapshot.

Submitting a benchmark report requires the request to carry `expected_report_version`, a non-optional field holding the report's own `version` as the client last observed it. If the report's `version` has advanced since — for instance because another writer returned the report and refreshed the DMA snapshot set — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412), since the client's view of which balances feed the aggregation is stale.

Both fields are mandatory on their respective requests; omitting one is a scalar-constraint failure under `ERR_VALIDATION`. No endpoint other than these two accepts a version field.

### 2.11. Segregation of Duties

Three transitions carry a hard segregation rule, anchored on the `X-User-ID` recorded at an earlier step. Finalizing a water balance period requires the acting analyst's `X-User-ID` to differ from the period's `created_by_user_id`. Verifying a leak repair requires the acting supervisor's `X-User-ID` to differ from the leak's `reported_by_user_id`. Approving a billing adjustment on an unauthorized-consumption case requires the acting director's `X-User-ID` to differ from the case's `substantiated_by_user_id`. A violation of any of the three is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.12. Audit Trail

Every mutating operation — every create, every state transition, and every system-driven transition — appends an **audit event**. An audit event records `entity_type` (the name of the entity mutated), `entity_id` (the identifier of the mutated row), `action` (the transition or operation name), `actor_user_id` and `actor_role` (the acting user's headers; system-driven transitions record the literal string `system` as both `actor_user_id` and `actor_role`), and `detail` (a before/after snapshot of the changed fields, carried under `before` and `after` keys). The `action` vocabulary is fixed: DistrictMeteredArea — CREATE; WaterBalancePeriod — CREATE, SUBMIT, FINALIZE, SUPERSEDE; NightFlowAssessment — CREATE, ANALYZE, VOID; LeakSurvey — CREATE, START, COMPLETE, CANCEL; Leak — CREATE, VERIFY, SCHEDULE_REPAIR, COMPLETE_REPAIR, VERIFY_REPAIR, REOPEN, WITHDRAW; CustomerMeter — CREATE, FLAG_REPLACEMENT, REPLACE, RETIRE, and UPDATE for the accuracy-test completion cascade; MeterAccuracyTest — CREATE, COMPLETE, CANCEL; UnauthorizedConsumptionCase — CREATE, BEGIN_EVIDENCE, SUBSTANTIATE, CLOSE_UNFOUNDED, CLOSE, PROPOSE_ADJUSTMENT, APPROVE_ADJUSTMENT, REJECT_ADJUSTMENT, POST_ADJUSTMENT; PressureProject — CREATE, APPROVE, REJECT, ACTIVATE, COMMISSION; InterventionProposal — CREATE, SUBMIT, APPROVE, REJECT, ARCHIVE; BenchmarkReport — CREATE, SUBMIT, ACCEPT, RETURN. Audit events are immutable and append-only. They may be listed by `ProgramDirector` and `RegulatorLiaison`, with optional filters on `entity_type`, `entity_id`, and `actor_user_id`.

## 3. Business Logic & Workflows

### 3.1. Establishing District Metered Areas

The program's unit of organization is the **District Metered Area**, a hydraulically discrete zone of the distribution network. A `ProgramDirector` registers a DMA by supplying a short `code` (unique across the utility, between 3 and 40 characters), a human-readable `name`, the `connection_count` of billed service connections inside the zone (at least 1), the `mains_length_km` of distribution mains in kilometres (strictly greater than zero), and a `target_nrw_pct` expressing the program's NRW-percentage goal for the zone (at least 0 and strictly below 100). A duplicate `code` is rejected with `ERR_DUPLICATE`. New DMAs begin with `posture` `OPEN`, no finalized balance, and an `open_leak_count` of zero.

Two derived figures ride on every DMA. `latest_nrw_pct` reports the audited NRW percentage of the DMA's most recently finalized water balance period — specifically, when a period is finalized it becomes the source of `latest_nrw_pct` if its `period_end` is the latest among the DMA's finalized periods (ties on `period_end` broken in favor of the earliest-created period) — and is null until some period has been finalized. `open_leak_count` counts the DMA's leaks — across all of its surveys — whose status sits in the open set `REPORTED`, `VERIFIED`, `REPAIR_SCHEDULED`, or `REOPENED`; notably, a repaired-but-not-yet-verified leak has already left the open set. Both figures recompute as the underlying children change, as described in §3.2 and §3.4.

DMAs may be listed by any role, with optional filters on `posture` and `code`, and each DMA exposes reverse-collection views of its balance periods, night-flow assessments, leak surveys, customer meters, unauthorized-consumption cases, pressure projects, and intervention proposals, each listable with a `status` filter where the child has a lifecycle (and with additional filters noted in §4).

### 3.2. The Water Balance: From Draft to Audited Figures

The water balance is the program's core accounting instrument. A `UtilityAnalyst` opens a **water balance period** against a DMA by providing the `dma_id`, the `period_start` (inclusive) and `period_end` (exclusive) of the accounting window as ISO 8601 UTC instants, and five measured or estimated volumes in cubic metres: `system_input_volume_m3` (water entering the DMA during the period, strictly greater than zero), `billed_authorized_m3` (metered plus unmetered billed consumption, at least zero), `unbilled_authorized_m3` (legitimate but unbilled uses such as firefighting and mains flushing, at least zero), `unauthorized_consumption_m3` (the estimated theft component of apparent losses, at least zero), and `metering_inaccuracy_m3` (the estimated customer-metering error component of apparent losses, at least zero). Because creation is OCC-guarded, the request must also carry `expected_dma_version` as described in §2.10, and the parent DMA must not be `FROZEN`.

Intervals are half-open: `period_end` must fall strictly after `period_start`, and two balance periods for the same DMA whose statuses lie in `DRAFT`, `SUBMITTED`, or `FINALIZED` must never overlap — though adjacent periods sharing exactly one boundary instant are permitted, since the end of one period may coincide with the start of the next. Violations surface as `ERR_WINDOW_CONFLICT`. A new period starts in `DRAFT` with `created_by_user_id` stamped from the acting analyst's header; creation populates the computed fields described below under the provisional variant, appends an audit event, and — because the DMA gains a child — increments the parent DMA's `version` by one.

Four quantities derive from the five input volumes. The non-revenue water volume `nrw_volume_m3` is the system input volume minus the billed authorized consumption. The apparent loss `apparent_loss_m3` is the sum of the unauthorized-consumption and metering-inaccuracy components. The raw real-loss remainder is what is left of the NRW volume after subtracting the unbilled authorized consumption and the apparent losses; because a negative remainder signals internally inconsistent inputs, the stored `real_loss_m3` is that remainder clamped at zero — the larger of the raw remainder and zero — while the negativity itself is enforced at submission time. The base NRW percentage is the NRW volume divided by the system input volume, multiplied by 100. While the period is in `DRAFT` or `SUBMITTED`, the stored `nrw_pct` is exactly this base percentage, rounded half-up to 2 decimal places — the **provisional variant**.

Submission moves a period from `DRAFT` to `SUBMITTED` and is allowed only while the parent DMA is not `FROZEN` and the computed `real_loss_m3` remainder reconciles — that is, the billed authorized, unbilled authorized, and apparent-loss components together must not exceed the system input volume; a period whose raw remainder would be negative is rejected at submission with `ERR_BALANCE_INCONSISTENT` (HTTP 422). Submission recomputes the provisional figures, recomputes the DMA's posture (which may move `OPEN` to `RESTRICTED`), increments the period's `version` by one, and appends an audit event.

Finalization moves a period from `SUBMITTED` to `FINALIZED` and performs the program's audit-grade recomputation. The acting analyst must differ from `created_by_user_id` per §2.11, and the parent DMA must not be `FROZEN`. At finalization the `nrw_pct` is recomputed under the **audited variant**: a confidence adjustment is subtracted from the base percentage, where the adjustment is the smaller of one-half of a percentage point (0.50) and one tenth of the base percentage itself, and the result is rounded half-up to 2 decimal places — so identical inputs report a slightly lower NRW once audited. Finalization also computes the period's `ili`, the **Infrastructure Leakage Index**, which is null on unfinalized periods. The ILI compares the DMA's current annual real losses against an unavoidable annual real-loss baseline: the baseline UARL, in cubic metres per year, is the sum of 18 per service connection, 0.8 per kilometre of mains, and 25 times the standard average zone pressure of 40 metres of head, with the sum divided by 1000 and then multiplied by 365; the current annual real loss is the period's `real_loss_m3` scaled by 365 divided by the period's length in whole days (the count of days between `period_start` and `period_end`; a period shorter than one whole day counts as one day); the ratio of the two is rounded half-up to 2 decimal places and, should the rounded value fall below 0.01, floored at 0.01. Finalization then updates the parent DMA: `latest_nrw_pct` is set from this period when its `period_end` is the latest among finalized siblings, the posture is recomputed (which may release `RESTRICTED` back to `OPEN`), and any previously finalized period whose window overlaps the newly finalized one is superseded — moved from `FINALIZED` to `SUPERSEDED` by the system, keeping the audited `nrw_pct` and `ili` values it computed at its own finalize time, while `latest_nrw_pct` is recomputed over the remaining finalized, non-superseded periods. Finalization increments the period's `version` by one, and the DMA's `version` advances once for each derived-field recompute that changes a stored value (per §2.4 and §2.6), so the DMA's `version` may advance by more than one at finalization; audit events are appended. A supersession appends its own audit event and increments the superseded period's `version` by one.

Balance periods may be listed across the program with optional `dma_id` and `status` filters, or per DMA through the reverse collection noted in §3.1.

### 3.3. Night-Flow Monitoring and Leak Detection Surveys

When a balance shows elevated real losses, field work begins with measurement. A `UtilityAnalyst` records a **night-flow assessment** against a DMA, capturing the `dma_id`, the observation window `window_start` (inclusive) and `window_end` (exclusive), the `measured_mnf_lps` minimum night flow in litres per second (at least zero), and the `expected_legitimate_night_use_lps` allowance for legitimate night consumption (at least zero). A window must last at least 2 hours and at most 6 hours, and windows for the same DMA must not overlap and must respect a one-hour buffer in both directions: a new window's `window_start` must be at least one hour after the `window_end` of every earlier window of the DMA, and its `window_end` must be at least one hour before the `window_start` of every later window, with a gap of exactly one hour permitted; assessments in `VOID` status are exempt from this check. Breaches are rejected with `ERR_WINDOW_CONFLICT`. A new assessment starts in `RECORDED`, with `net_night_flow_lps`, `net_night_flow_pct`, and `leak_signal` null until analysis.

Analysis moves an assessment from `RECORDED` to `ANALYZED` and computes three derived values. `net_night_flow_lps` is the measured minimum night flow minus the legitimate-use allowance, floored at zero. `net_night_flow_pct` expresses that net flow as a percentage of the DMA's average daily inflow implied by its latest finalized, non-superseded balance period (selected by latest `period_end`, with ties broken in favor of the earliest-`created_at` period): the average daily inflow in litres per second is the period's `system_input_volume_m3` converted to litres by multiplying by 1000, divided by the number of seconds in the period (its length in days multiplied by 86400); the percentage is the net night flow divided by that inflow, multiplied by 100, rounded half-up to 2 decimal places. When no finalized balance exists for the DMA, `net_night_flow_pct` is null. The `leak_signal` then classifies the assessment: `CRITICAL` when the net night flow reaches 15.0 litres per second or more, or when a non-null `net_night_flow_pct` reaches 20.0 or more; `ELEVATED` when the net night flow reaches 5.0 litres per second or more, or a non-null percentage reaches 8.0 or more; otherwise `NONE`. All four thresholds are inclusive. A `CRITICAL` signal is deliberately a signal only — no survey is auto-created and `open_leak_count` is untouched; field deployment remains a human decision. An assessment that should never have been recorded can instead be moved from `RECORDED` to `VOID`, a terminal state; the status vocabulary also includes the terminal `SUPERSEDED`, reserved for an analyzed assessment displaced by later analysis of an overlapping window. Both transitions append audit events.

Surveys are the field response. A `FieldSupervisor` plans a **leak survey** by supplying the `dma_id`, a `planned_start` (inclusive) and `planned_end` (exclusive, strictly after `planned_start`), the detection `method` — one of `ACOUSTIC`, `CORRELATOR`, `SATELLITE`, `STEP_TEST`, or `NOISE_LOGGER` — and the `crew_lead_user_id` of the supervising FieldSupervisor as an audit anchor. Surveys for the same DMA whose statuses are `PLANNED` or `IN_FIELD` must not overlap, again as half-open intervals with touching boundaries allowed; conflicts are `ERR_WINDOW_CONFLICT`. A new survey is `PLANNED`.

Starting field work moves a survey from `PLANNED` to `IN_FIELD` and requires two preconditions: the parent DMA's posture must be exactly `OPEN`, and the logical clock must have reached the survey's `planned_start` — a start attempted before then is rejected with `ERR_INVALID_STATE` (HTTP 409). Completing a survey moves it from `IN_FIELD` to `COMPLETED` and freezes the campaign: the request supplies `coverage_pct`, the percentage of the DMA's mains length actually surveyed (strictly greater than 0 and at most 100), which is stored on the survey (`coverage_pct` is null until completion). Completion is permitted regardless of whether the survey's leaks remain open — leaks in `REPORTED`, `VERIFIED`, `REPAIR_SCHEDULED`, or `REOPENED` do not block completion; it is the coverage figure, not the repair pipeline, that completion freezes. The survey's `leaks_found_count` reports how many leak rows belong to the survey in any status except `WITHDRAWN`.

Cancellation guards depend on the survey's stage. Cancelling a `PLANNED` survey requires that no leak rows exist under it at all; cancelling an `IN_FIELD` survey requires that every leak under it has reached a terminal state (`VERIFIED_REPAIR` or `WITHDRAWN`). A cancellation attempted against leaks in any other configuration is rejected with `ERR_CHILDREN_OPEN` (HTTP 409); a successful cancellation moves the survey to `CANCELLED` and appends an audit event.

### 3.4. Leak Lifecycle, Repair Prioritization, and Rework

While a survey is `IN_FIELD`, its `FieldSupervisor` reports **leaks**: each report carries the `survey_id`, a free-text `location_description` within the DMA, the `estimated_loss_lps` loss rate in litres per second (strictly greater than zero), the `detected_at` field-detection instant, and a `repair_cost_estimate` in currency units (at least zero). Reporting against a survey that is not `IN_FIELD` is rejected with `ERR_INVALID_STATE`. A new leak begins `REPORTED`, with `reported_by_user_id` stamped from the acting supervisor, and its derived metrics computed immediately: `annualized_loss_m3` is the estimated loss rate multiplied by 86400 seconds per day and 365 days per year, divided by 1000 to convert litres to cubic metres; and the `repair_priority_score` with its `priority_band`, computed as follows.

The priority score ranks leaks by the value of water saved per unit of repair spend. The annual value of the loss is the `annualized_loss_m3` multiplied by the program water value of 1.20 currency units per cubic metre. The cost ratio is that annual value divided by the larger of the `repair_cost_estimate` and a cost floor of 1.0. The base score is the cost ratio scaled by 2.0, capped at 100. When the leak's DMA has a pressure project in `ACTIVE` status, a pressure-management bonus multiplies the score by 1.25, reflecting that reduced zone pressure will make the repair partly self-funding. The resulting `repair_priority_score` is rounded half-up to 2 decimal places. The `priority_band` then buckets the score: `P1` when the score is 50.0 or more, `P2` when it is 20.0 or more but below 50.0, and `P3` below 20.0; band boundaries are inclusive.

Verification moves a leak from `REPORTED` to `VERIFIED` — permitted only while the parent survey is still `IN_FIELD` — and recomputes the score and band. Scheduling moves a `VERIFIED` leak to `REPAIR_SCHEDULED`; scheduling does not recompute the score or band, which persist as last computed. Completing the repair moves it from `REPAIR_SCHEDULED` to `REPAIRED` and requires the request to supply the `actual_repair_cost` (at least zero); a completion attempted without it is rejected with `ERR_MISSING_PREREQUISITE` (HTTP 422). The supplied cost is stored, the DMA's `open_leak_count` is recomputed, and an audit event is appended. A repaired leak then faces one of two fates. Verification of the repair — which must be performed by a supervisor whose `X-User-ID` differs from the leak's `reported_by_user_id`, with violations rejected as `ERR_SEGREGATION_OF_DUTIES` per §2.11 — moves it to the terminal `VERIFIED_REPAIR` state, recomputing `open_leak_count`; when that verification leaves every sibling leak under the survey terminal, the survey itself may be completed, though completion always remains an explicit act rather than an automatic cascade. Alternatively, a repair that fails inspection is reopened: the leak moves from `REPAIRED` to `REOPENED`, its score is recomputed from the same formula with an additional rework penalty multiplying the result by 1.10, its previously recorded `actual_repair_cost` is retained, and `open_leak_count` is recomputed. A reopened leak re-enters scheduling — `REOPENED` to `REPAIR_SCHEDULED` — and proceeds through the repair cycle again. Finally, a leak reported in error can be withdrawn from either `REPORTED` or `VERIFIED` into the terminal `WITHDRAWN` state, recomputing `open_leak_count`.

Leaks are listable per survey (with optional `status` and `priority_band` filters) and across the program as a cross-survey repair backlog view filterable by `survey_id`, `dma_id`, `status`, and `priority_band`. Every transition appends an audit event.

### 3.5. Customer Meters, Accuracy Testing, and Replacement Policy

Apparent losses are attacked through the meter fleet. A `MeterTechnician` registers a **customer meter** with its `dma_id`, the manufacturer `serial_number` (unique across the utility, with duplicates rejected as `ERR_DUPLICATE`), the nominal `size_mm` — which must be one of 15, 20, 25, 40, 50, 100, or 150 millimetres — the `installed_at` installation date, and an optional `replacement_policy` selecting the replacement lane: `AGE_BASED` replaces on age alone, `ACCURACY_BASED` replaces on a failed accuracy test alone, and `HYBRID` applies whichever trigger fires first; omitted, the policy defaults to `ACCURACY_BASED`. A new meter begins `IN_SERVICE`, with `last_test_accuracy_pct` null until a test completes and `replacement_due` evaluated at registration per the policy rule below.

The replacement-due rule runs on two lanes. The age lane computes the meter's age in years as the whole days between the current logical-clock instant and `installed_at`, divided by 365.25 and truncated to an integer; the age trigger trips when that age reaches the program limit of 15 years — the boundary is inclusive. The accuracy lane trips when the meter's most recent completed accuracy test (selected by latest `tested_at`, ties broken by earliest `created_at`) exists and its `result` is `FAIL`. Under `AGE_BASED`, `replacement_due` is the age trigger alone; under `ACCURACY_BASED`, the accuracy trigger alone; under `HYBRID`, the two combined with logical-or. When the rule flips true — at clock advance for the age lane (§2.5), or at test completion for the accuracy lane — the meter moves from `IN_SERVICE` to `FLAGGED_FOR_REPLACEMENT` automatically; a technician may also flag a meter manually through the same transition, which changes only the status and does not itself set `replacement_due`. Meters never gate DMA posture, so flagging leaves the parent DMA untouched; an audit event is appended either way.

Accuracy testing is the accuracy lane's instrument. A technician schedules a **meter accuracy test** against a meter — permitted whatever the meter's current status — by supplying the `meter_id`, the `tested_at` test instant (which must not precede the meter's `installed_at`; earlier dates are rejected with `ERR_VALIDATION`), and the `flow_rate_lps` test flow rate in litres per second (strictly greater than zero). The test begins `SCHEDULED`. Completing a test — allowed only while the parent meter is `IN_SERVICE` or `FLAGGED_FOR_REPLACEMENT`, otherwise `ERR_INVALID_STATE` — requires the technician to supply the `registered_volume_m3` registered by the meter and the `reference_volume_m3` delivered by the reference apparatus, both strictly greater than zero. The `accuracy_pct` is the registered volume divided by the reference volume, multiplied by 100 and rounded half-up to 2 decimal places; the `result` is `PASS` when the accuracy is at least 98.0 and at most 102.0 — a test landing exactly on either boundary passes — and `FAIL` otherwise, remaining null until completion. Completion writes `last_test_accuracy_pct` onto the meter, and when the `result` is `FAIL` and the meter's `replacement_policy` is `ACCURACY_BASED` or `HYBRID`, the meter cascades from `IN_SERVICE` to `FLAGGED_FOR_REPLACEMENT`; audit events are appended on both the test and the meter. A scheduled test that will not run moves from `SCHEDULED` to `CANCELLED`.

Replacement is the lane's terminus. Replacing a `FLAGGED_FOR_REPLACEMENT` meter requires the request to supply the replacement `serial_number`, which must be unique across the utility on pain of `ERR_DUPLICATE`. The operation retires the old row into `REPLACED` status and, in the same act, creates the successor meter: `IN_SERVICE`, carrying the replacement serial, with `dma_id`, `size_mm`, and `replacement_policy` copied from its predecessor and `installed_at` stamped from the current logical clock. The operation returns `200 OK` with the successor meter in the data field. Audit events are appended on both rows. A meter may also leave service without replacement: retirement moves an `IN_SERVICE` meter to `RETIRED`, but only when no accuracy test for it remains `SCHEDULED`; attempting retirement with a scheduled test outstanding is rejected with `ERR_INVALID_STATE`. Both `REPLACED` and `RETIRED` are terminal. Meters are listable per DMA with optional `status` and `replacement_due` filters — the boolean `replacement_due` filter accepts the strings `true` and `false`, case-insensitively — and each meter exposes the reverse collection of its accuracy tests, filterable by `status`.

### 3.6. Unauthorized Consumption Investigations and Billing Adjustments

Suspected theft follows a two-dimensional case model. An `Investigator` opens an **unauthorized-consumption case** with the `dma_id` of the DMA where the consumption occurred, an external `service_location_ref` identifying the service location under investigation, and the `opened_at` instant. From that moment the case evolves along two parallel dimensions. The investigation dimension, `investigation_status`, begins `OPEN`; the billing dimension, `billing_adjustment_status`, begins `NONE`. The two advance independently except that the billing dimension cannot leave `NONE` until the investigation has been substantiated.

Beginning evidence gathering moves the investigation from `OPEN` to `EVIDENCE_GATHERING`. From there the case resolves one of two ways. Substantiation moves it to `SUBSTANTIATED` and requires the request to supply the `estimated_loss_m3`, the estimated unauthorized volume (at least zero); a substantiation without it is rejected with `ERR_MISSING_PREREQUISITE`. The supplied volume is stored, `substantiated_by_user_id` is stamped from the acting investigator, and the value is surfaced as an advisory suggestion for the DMA's next `DRAFT` water balance — advisory only, with no automatic write. Alternatively, an investigation that finds nothing moves from `EVIDENCE_GATHERING` to `UNFOUNDED`.

Case closure depends on both dimensions. An `UNFOUNDED` case closes only while its billing dimension is still `NONE`. A `SUBSTANTIATED` case closes only when its billing dimension rests at `NONE`, `REJECTED`, or `POSTED` — a case with an adjustment still `PROPOSED` or `APPROVED` cannot be closed. A close attempted in violation of either guard is rejected with `ERR_INVALID_STATE` (HTTP 409). `CLOSED` is terminal for the investigation dimension.

The billing dimension recovers revenue on substantiated cases. Proposing an adjustment moves billing from `NONE` to `PROPOSED`; it is gated on the investigation being `SUBSTANTIATED` and requires the request to supply the `proposed_adjustment_amount`, a back-billing amount strictly greater than zero, which is stored on the case. A `ProgramDirector` then decides: approval moves billing from `PROPOSED` to `APPROVED` and enforces §2.11 — the director's `X-User-ID` must differ from `substantiated_by_user_id`, with violations rejected as `ERR_SEGREGATION_OF_DUTIES` — while rejection moves it from `PROPOSED` to `REJECTED`. Posting, performed by an `Investigator`, moves an `APPROVED` adjustment to `POSTED` and stamps the `posted_adjustment_amount` equal to the `proposed_adjustment_amount`; before posting, and on any non-posted case, `posted_adjustment_amount` remains null. Every transition on either dimension appends an audit event. Cases are listable per DMA with optional `investigation_status` and `billing_adjustment_status` filters.

### 3.7. Pressure Management Projects

Because leakage varies with pressure, sustained pressure reduction is one of the program's structural interventions. A `UtilityAnalyst` drafts a **pressure project** for a DMA with the `dma_id`, a project `name`, the planned field-work window `planned_start` (inclusive) and `planned_end` (exclusive, strictly after `planned_start`; violations are `ERR_WINDOW_CONFLICT`), the `baseline_pressure_m` average zone pressure before intervention in metres of head (strictly greater than zero), and the `target_pressure_m` after intervention (strictly greater than zero and strictly below the baseline; a target at or above the baseline is rejected with `ERR_VALIDATION`). A new project is `PROPOSED`.

A `ProgramDirector` decides the draft: approval moves the project from `PROPOSED` to `APPROVED` and, per §2.6, is permitted only while the DMA's posture is exactly `OPEN`; rejection moves it from `PROPOSED` to `REJECTED`. A project already `APPROVED` can still be withdrawn to `REJECTED` before activation. Activation moves an `APPROVED` project to `ACTIVE` once the logical clock has reached its `planned_start` (an activation attempted before then is rejected with `ERR_INVALID_STATE`, HTTP 409), and — because active field work constrains the district — recomputes the DMA's posture, moving an `OPEN` district to `RESTRICTED`.

Commissioning closes the loop. It moves an `ACTIVE` project to the terminal `COMMISSIONED` state and requires the request to supply the `measured_pressure_m`, the measured post-commissioning average pressure (strictly greater than zero and no greater than the baseline; a missing measurement is `ERR_MISSING_PREREQUISITE`, and one exceeding the baseline is `ERR_VALIDATION`). Two derived figures are then computed. The `pressure_reduction_pct` is the baseline minus the measured pressure, divided by the baseline, multiplied by 100, rounded half-up to 2 decimal places. The `estimated_leak_reduction_m3_per_year` applies the fixed-and-variable-area-discharge exponent: when a latest finalized, non-superseded balance period exists for the DMA (selected by latest `period_end`, ties broken by earliest `created_at`), the period's `real_loss_m3` is first annualized — multiplied by 365 divided by that period's length in days — and the reduction estimate is that annualized loss multiplied by one minus the ratio of measured to baseline pressure raised to the 1.15 power, rounded half-up to a whole cubic metre; when no such finalized balance exists, the estimate is null. Commissioning also recomputes the DMA's posture, releasing `RESTRICTED` back to `OPEN` when no other child gates it, and appends an audit event.

### 3.8. Intervention Proposals and Benefit–Cost Economics

Every candidate intervention competes for capital on its economics. A `UtilityAnalyst` drafts an **intervention proposal** against a DMA — while the DMA is not `FROZEN` — with the `dma_id`, the intervention `kind` (one of `LEAK_REPAIR_PROGRAM`, `METER_REPLACEMENT_PROGRAM`, `PRESSURE_MANAGEMENT`, or `UNAUTHORIZED_USE_ENFORCEMENT`), the up-front `capital_cost` (at least zero), the recurring `annual_om_cost` operating and maintenance cost (at least zero), and the `expected_volume_saved_m3_per_year` (strictly greater than zero). A new proposal is `DRAFT`, and its economics are computed immediately under the provisional variant.

The benefit–cost rule evaluates in a pinned order: gross benefit first, then discounting, then costs, then the ratio. The annual gross benefit is the expected annual volume saved multiplied by a marginal water value that depends on which volume tier the saving falls into: below 50,000 cubic metres per year the value is 1.10 per cubic metre; from 50,000 up to but excluding 200,000 the value is 1.30; at 200,000 and above the value is 1.55 — tier boundaries are inclusive at the lower edge. The benefit stream is then discounted over a 20-year analysis horizon: the present-value factor is the sum, over each year from 1 through 20, of one divided by (1 plus the discount rate) raised to that year's power, itself rounded half-up to 6 decimal places before use. The discount rate is the variant's signature: while a proposal is `DRAFT` or `SUBMITTED`, the **provisional** variant uses a screening-grade 7 percent; once approved, the **bankable** variant uses an investment-grade 4 percent, so identical inputs always yield a strictly higher ratio once bankable. The present value of benefits is the annual gross benefit multiplied by the factor; the present value of costs is the `capital_cost` plus the `annual_om_cost` multiplied by the factor. The `benefit_cost_ratio` is the present value of benefits divided by the larger of the present value of costs and a cost floor of 1.0, rounded half-up to 2 decimal places. The `payback_years` is the simple payback: the annual net benefit is the annual gross benefit minus the `annual_om_cost`, and when that net benefit is zero or negative the payback is null; otherwise it is the `capital_cost` divided by the annual net benefit, rounded half-up to 1 decimal place.

Submission moves a proposal from `DRAFT` to `SUBMITTED` — again gated on the DMA not being `FROZEN` — and recomputes the ratio under the provisional variant. A `ProgramDirector` then decides. Approval moves the proposal from `SUBMITTED` to `APPROVED` and enforces the program's investment gate: the benefit–cost ratio as last computed at submission must be at least 1.00 — the boundary is inclusive — or the approval is rejected with `ERR_BCR_BELOW_THRESHOLD` (HTTP 422). Upon approval the ratio is recomputed under the bankable variant, and a supersede cascade fires: every other proposal of the same `kind` for the same DMA currently sitting in `APPROVED` is moved by the system to `ARCHIVED`, keeping the bankable ratio it computed at its own approval time; the archival appends its own audit event. Rejection moves a `SUBMITTED` proposal to `REJECTED`. `REJECTED` and `ARCHIVED` are terminal. Proposals are listable per DMA with optional `status` and `kind` filters.

### 3.9. Benchmark Reporting to the State

The program's year culminates in the regulatory filing. A `RegulatorLiaison` drafts a **benchmark report** with the `reporting_year` (the calendar year covered, no earlier than 2000), the `reporting_period_start` (inclusive) and `reporting_period_end` (exclusive, strictly after the start), and the `dma_ids` array naming every DMA the report covers; each element of `dma_ids` must resolve to an existing DMA on pain of `ERR_NOT_FOUND`. A new report is `DRAFT`, and its aggregate fields — `utility_nrw_pct`, `utility_ili`, and `per_dma_breakdown` — remain unpopulated until submission.

Submission moves a report from `DRAFT` to `SUBMITTED` and is the report's moment of truth. The request must carry `expected_report_version` per §2.10. The `dma_ids` array must be non-empty, and every listed DMA must have a qualifying balance: a finalized, non-superseded water balance period whose half-open window lies fully inside the reporting window — a DMA without one blocks submission with `ERR_MISSING_PREREQUISITE`. On submission the snapshot is computed and frozen. For each listed DMA, the qualifying balance is selected — when several qualify, the one with the latest `period_end`, ties broken by earliest `created_at` — and a breakdown row is recorded carrying that DMA's `dma_id`, `dma_code`, `nrw_pct`, `ili`, and `real_loss_m3`; the rows of `per_dma_breakdown` are ordered deterministically by the DMA `code` in ascending lexicographic order, which admits no ties because codes are unique. The `utility_nrw_pct` is volume-weighted, not an arithmetic mean of percentages: the sum of the selected balances' `nrw_volume_m3` divided by the sum of their `system_input_volume_m3`, multiplied by 100. The `utility_ili` is likewise aggregate-first: the sum of the selected balances' annualized real losses divided by the sum of their unavoidable annual losses, taken over exactly those DMAs whose `ili` is non-null. Both figures are rounded half-up to 2 decimal places. Submission then freezes the districts: every listed DMA's posture is recomputed to `FROZEN`, whether it stood at `OPEN` or `RESTRICTED`. The report's `version` increments by one and an audit event is appended.

The regulator's reply resolves the report. Acceptance moves a `SUBMITTED` report to the terminal `ACCEPTED` state and, per §2.6, leaves the DMA freeze in place. Return moves it from `SUBMITTED` to `RETURNED` and compensates: every listed DMA's posture is recomputed, releasing `FROZEN` districts back to `OPEN` wherever no other gating child state holds. A returned report may be corrected and resubmitted — `RETURNED` back to `SUBMITTED` — under the same preconditions and OCC guard as the original submission; resubmission recomputes and re-freezes the snapshot and re-applies the district freeze. Reports are listable with optional `status`, `reporting_year`, and `dma_ids` filters — the `dma_ids` filter takes a single DMA identifier and matches reports whose `dma_ids` array contains it — and each report fetch returns the frozen `per_dma_breakdown` exactly as captured at submission.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including every state transition, return `200 OK`. All endpoints sit under the `/nrw` prefix. Request and response payloads are not repeated here — they are defined by the narratives in §3 — and authorized roles are listed exactly as enforced by §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/nrw/_clock/set_current_utc` | Set the server's logical clock (initial reading 2026-08-01T00:00:00Z) | ProgramDirector |
| POST | `/nrw/dmas` | Create a DMA | ProgramDirector |
| GET | `/nrw/dmas` | List DMAs with pagination and optional filters | ProgramDirector, UtilityAnalyst, FieldSupervisor, MeterTechnician, Investigator, RegulatorLiaison |
| GET | `/nrw/dmas/{id}` | Fetch one DMA including computed posture, latest_nrw_pct, open_leak_count | ProgramDirector, UtilityAnalyst, FieldSupervisor, MeterTechnician, Investigator, RegulatorLiaison |
| GET | `/nrw/dmas/{id}/water-balance-periods` | List balance periods of a DMA | ProgramDirector, UtilityAnalyst, RegulatorLiaison |
| GET | `/nrw/dmas/{id}/night-flow-assessments` | List night-flow assessments of a DMA | ProgramDirector, UtilityAnalyst |
| GET | `/nrw/dmas/{id}/leak-surveys` | List leak surveys of a DMA | ProgramDirector, UtilityAnalyst, FieldSupervisor |
| GET | `/nrw/dmas/{id}/customer-meters` | List customer meters of a DMA | ProgramDirector, MeterTechnician, UtilityAnalyst |
| GET | `/nrw/dmas/{id}/unauthorized-consumption-cases` | List unauthorized-consumption cases of a DMA | ProgramDirector, Investigator |
| GET | `/nrw/dmas/{id}/pressure-projects` | List pressure projects of a DMA | ProgramDirector, UtilityAnalyst |
| GET | `/nrw/dmas/{id}/intervention-proposals` | List intervention proposals of a DMA | ProgramDirector, UtilityAnalyst |
| POST | `/nrw/water-balance-periods` | Create a water balance period (DRAFT) with OCC against the parent DMA | UtilityAnalyst |
| GET | `/nrw/water-balance-periods` | List balance periods with filters | ProgramDirector, UtilityAnalyst, RegulatorLiaison |
| GET | `/nrw/water-balance-periods/{id}` | Fetch one balance period | ProgramDirector, UtilityAnalyst, RegulatorLiaison |
| POST | `/nrw/water-balance-periods/{id}/submit` | Move a balance period from DRAFT to SUBMITTED | UtilityAnalyst |
| POST | `/nrw/water-balance-periods/{id}/finalize` | Move a balance period from SUBMITTED to FINALIZED with segregation-of-duties check | UtilityAnalyst |
| POST | `/nrw/night-flow-assessments` | Record a minimum-night-flow assessment window (RECORDED) | UtilityAnalyst |
| GET | `/nrw/night-flow-assessments/{id}` | Fetch one assessment | ProgramDirector, UtilityAnalyst |
| POST | `/nrw/night-flow-assessments/{id}/analyze` | Move an assessment from RECORDED to ANALYZED, computing net flows and leak signal | UtilityAnalyst |
| POST | `/nrw/night-flow-assessments/{id}/void` | Move an assessment from RECORDED to VOID | UtilityAnalyst |
| POST | `/nrw/leak-surveys` | Plan a leak survey (PLANNED) | FieldSupervisor |
| GET | `/nrw/leak-surveys/{id}` | Fetch one survey | ProgramDirector, UtilityAnalyst, FieldSupervisor |
| GET | `/nrw/leak-surveys/{id}/leaks` | List leaks of a survey | ProgramDirector, UtilityAnalyst, FieldSupervisor |
| POST | `/nrw/leak-surveys/{id}/start` | Move a survey from PLANNED to IN_FIELD (requires DMA posture OPEN and clock at planned start) | FieldSupervisor |
| POST | `/nrw/leak-surveys/{id}/complete` | Move a survey from IN_FIELD to COMPLETED with coverage_pct | FieldSupervisor |
| POST | `/nrw/leak-surveys/{id}/cancel` | Cancel a PLANNED or IN_FIELD survey under the child-state guard | FieldSupervisor |
| POST | `/nrw/leaks` | Report a leak under a survey (REPORTED); survey must be IN_FIELD | FieldSupervisor |
| GET | `/nrw/leaks` | List leaks with filters (cross-survey repair backlog view) | ProgramDirector, UtilityAnalyst, FieldSupervisor |
| GET | `/nrw/leaks/{id}` | Fetch one leak | ProgramDirector, UtilityAnalyst, FieldSupervisor |
| POST | `/nrw/leaks/{id}/verify` | Move a leak from REPORTED to VERIFIED | FieldSupervisor |
| POST | `/nrw/leaks/{id}/schedule-repair` | Move a VERIFIED or REOPENED leak to REPAIR_SCHEDULED | FieldSupervisor |
| POST | `/nrw/leaks/{id}/complete-repair` | Move a leak from REPAIR_SCHEDULED to REPAIRED with actual_repair_cost | FieldSupervisor |
| POST | `/nrw/leaks/{id}/verify-repair` | Move a leak from REPAIRED to VERIFIED_REPAIR; actor must differ from the reporter | FieldSupervisor |
| POST | `/nrw/leaks/{id}/reopen` | Move a leak from REPAIRED to REOPENED (rework cycle with score penalty) | FieldSupervisor |
| POST | `/nrw/leaks/{id}/withdraw` | Move a REPORTED or VERIFIED leak to WITHDRAWN | FieldSupervisor |
| POST | `/nrw/customer-meters` | Register a customer meter (IN_SERVICE) | MeterTechnician |
| GET | `/nrw/customer-meters/{id}` | Fetch one meter | ProgramDirector, MeterTechnician, UtilityAnalyst |
| GET | `/nrw/customer-meters/{id}/accuracy-tests` | List accuracy tests of a meter | ProgramDirector, MeterTechnician, UtilityAnalyst |
| POST | `/nrw/customer-meters/{id}/flag-replacement` | Manually flag an IN_SERVICE meter for replacement | MeterTechnician |
| POST | `/nrw/customer-meters/{id}/replace` | Replace a FLAGGED_FOR_REPLACEMENT meter, spawning its successor | MeterTechnician |
| POST | `/nrw/customer-meters/{id}/retire` | Move an IN_SERVICE meter to RETIRED | MeterTechnician |
| POST | `/nrw/meter-accuracy-tests` | Schedule an accuracy test (SCHEDULED) | MeterTechnician |
| GET | `/nrw/meter-accuracy-tests/{id}` | Fetch one accuracy test | ProgramDirector, MeterTechnician, UtilityAnalyst |
| POST | `/nrw/meter-accuracy-tests/{id}/complete` | Complete a test, computing accuracy and cascading a FAIL to replacement flagging under applicable policies | MeterTechnician |
| POST | `/nrw/meter-accuracy-tests/{id}/cancel` | Cancel a SCHEDULED test | MeterTechnician |
| POST | `/nrw/unauthorized-consumption-cases` | Open an investigation (OPEN x NONE) | Investigator |
| GET | `/nrw/unauthorized-consumption-cases/{id}` | Fetch one case (both state dimensions) | ProgramDirector, Investigator |
| POST | `/nrw/unauthorized-consumption-cases/{id}/begin-evidence` | Move the investigation from OPEN to EVIDENCE_GATHERING | Investigator |
| POST | `/nrw/unauthorized-consumption-cases/{id}/substantiate` | Move the investigation from EVIDENCE_GATHERING to SUBSTANTIATED with estimated_loss_m3 | Investigator |
| POST | `/nrw/unauthorized-consumption-cases/{id}/close-unfounded` | Move the investigation from EVIDENCE_GATHERING to UNFOUNDED | Investigator |
| POST | `/nrw/unauthorized-consumption-cases/{id}/close` | Close an UNFOUNDED or SUBSTANTIATED case under the billing-dimension guard | Investigator |
| POST | `/nrw/unauthorized-consumption-cases/{id}/propose-adjustment` | Move billing from NONE to PROPOSED (gated on SUBSTANTIATED) | Investigator |
| POST | `/nrw/unauthorized-consumption-cases/{id}/approve-adjustment` | Move billing from PROPOSED to APPROVED; actor must differ from the substantiator | ProgramDirector |
| POST | `/nrw/unauthorized-consumption-cases/{id}/reject-adjustment` | Move billing from PROPOSED to REJECTED | ProgramDirector |
| POST | `/nrw/unauthorized-consumption-cases/{id}/post-adjustment` | Move billing from APPROVED to POSTED | Investigator |
| POST | `/nrw/pressure-projects` | Create a pressure management project (PROPOSED) | UtilityAnalyst |
| GET | `/nrw/pressure-projects/{id}` | Fetch one project | ProgramDirector, UtilityAnalyst |
| POST | `/nrw/pressure-projects/{id}/approve` | Move a project from PROPOSED to APPROVED (requires DMA posture OPEN) | ProgramDirector |
| POST | `/nrw/pressure-projects/{id}/reject` | Move a PROPOSED or APPROVED project to REJECTED | ProgramDirector |
| POST | `/nrw/pressure-projects/{id}/activate` | Move an APPROVED project to ACTIVE once the clock reaches planned start; restricts the DMA | ProgramDirector |
| POST | `/nrw/pressure-projects/{id}/commission` | Move an ACTIVE project to COMMISSIONED with measured_pressure_m | ProgramDirector |
| POST | `/nrw/intervention-proposals` | Draft an intervention proposal (DRAFT); provisional benefit-cost ratio computed | UtilityAnalyst |
| GET | `/nrw/intervention-proposals/{id}` | Fetch one proposal | ProgramDirector, UtilityAnalyst |
| POST | `/nrw/intervention-proposals/{id}/submit` | Move a proposal from DRAFT to SUBMITTED | UtilityAnalyst |
| POST | `/nrw/intervention-proposals/{id}/approve` | Move a proposal from SUBMITTED to APPROVED under the benefit-cost gate; archives superseded same-kind siblings | ProgramDirector |
| POST | `/nrw/intervention-proposals/{id}/reject` | Move a proposal from SUBMITTED to REJECTED | ProgramDirector |
| POST | `/nrw/benchmark-reports` | Create a benchmark report draft over a set of DMAs | RegulatorLiaison |
| GET | `/nrw/benchmark-reports` | List benchmark reports | ProgramDirector, UtilityAnalyst, RegulatorLiaison |
| GET | `/nrw/benchmark-reports/{id}` | Fetch one report including the frozen per-DMA breakdown | ProgramDirector, UtilityAnalyst, RegulatorLiaison |
| POST | `/nrw/benchmark-reports/{id}/submit` | Submit a DRAFT or RETURNED report with OCC; freezes the snapshot and the DMA postures | RegulatorLiaison |
| POST | `/nrw/benchmark-reports/{id}/accept` | Move a SUBMITTED report to ACCEPTED | RegulatorLiaison |
| POST | `/nrw/benchmark-reports/{id}/return` | Move a SUBMITTED report to RETURNED, compensating the DMA freeze | RegulatorLiaison |
| GET | `/nrw/audit-events` | List audit events with filters | ProgramDirector, RegulatorLiaison |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DMA_FROZEN` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
| `ERR_MISSING_PREREQUISITE` | 422 Unprocessable Entity |
| `ERR_BCR_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_BALANCE_INCONSISTENT` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CHILDREN_OPEN` | 409 Conflict |
