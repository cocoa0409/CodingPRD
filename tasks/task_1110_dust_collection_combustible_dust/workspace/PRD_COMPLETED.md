# Dust Compliance API — Product Requirements Document

## 1. Introduction

Facilities that handle combustible particulate solids operate under a layered compliance regime: NFPA 652 mandates a Dust Hazard Analysis (DHA) for every process handling combustible dust, NFPA 68 governs explosion vent sizing on dust collectors, NFPA 51B constrains hot work, and insurers and Authorities Having Jurisdiction (AHJs) conduct their own walkdowns with findings that must be tracked to closure. Facilities that fall behind on any of these threads — an overdue housekeeping audit, an undersized vent, a hot-work permit left open past its fire watch — accumulate latent risk that surfaces as incidents, insurance non-renewals, or regulatory stop-work orders.

This document specifies the **Dust Compliance API**, a multi-tenant compliance platform used by third-party NFPA 652 compliance contractors and their client facilities. The API manages the full operational loop: registering dust samples and their Kst classifications, sizing and commissioning collectors with adequate explosion venting, scheduling and recording housekeeping audits, issuing and supervising hot-work permits, ingesting AHJ/insurer inspection findings, scoping retrofit projects that remediate critical findings, and investigating incidents through CAPA closure.

A distinctive feature of the platform is its **site posture** — a single derived value (`COMPLIANT`, `CONDITIONAL`, `DEFICIENT`, or `STOP_WORK`) that aggregates critical findings, overdue housekeeping, active hot work, inadequate venting, open incidents, and retrofit projects in flight. Several dangerous operations are gated on posture: a site in `STOP_WORK` cannot commission collectors, return them to service, start hot work, or begin retrofit execution. Posture is recomputed automatically whenever the underlying counters change, and several workflows mutate posture as a side effect rather than as a direct client call.

The platform enforces strict segregation of duties. The engineer who authors a DHA may not approve it; the safety manager who issues a hot-work permit may not perform the work; the investigator leading an incident inquiry may not have issued a related hot-work permit. These rules are structural, not advisory, and violations are rejected with a dedicated error.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting operator and `X-User-Role` to specify their operational capacity. The system recognizes eight roles, spelled exactly as follows: `PlatformAdmin`, `ComplianceManager`, `ComplianceEngineer`, `SafetyManager`, `HotWorkPerformer`, `HousekeepingAuditor`, `InspectorUser`, and `IncidentInvestigator`.

When the `X-User-Role` header is missing or does not match one of the eight recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Every one of the eight roles requires `X-User-ID`: when `X-User-ID` is missing or empty for any recognized role, the request is likewise rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the role is recognized but is not permitted to invoke the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

**Identity semantics.** Every one of the eight roles is **opaque**: `X-User-ID` is an opaque operator identifier not tied to any persisted entity for `PlatformAdmin`, `ComplianceManager`, `ComplianceEngineer`, `SafetyManager`, `HotWorkPerformer`, `HousekeepingAuditor`, `InspectorUser`, and `IncidentInvestigator`. The server records `X-User-ID` onto specific fields where a workflow demands attribution — `author_id` and `approver_id` on a DHA, `auditor_id` on a HousekeepingAudit, `issuer_id` and `performer_id` on a HotWorkPermit, `investigation_lead_id` on an Incident, `owner_id` on a CAPAAction — but does not compare it to any entity's `id`. Segregation-of-duties checks compare these recorded identifiers against the calling `X-User-ID` (for example, the `approver_id` written at DHA approval must differ from the `author_id` recorded at DHA creation).

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

Requests to unknown paths, and requests whose HTTP method is not supported by an otherwise-matching path, are rejected with `ERR_NOT_FOUND` (HTTP 404). Malformed requests that fail before endpoint logic runs (for example, an unparseable JSON body rejected by the framework) surface as `ERR_INVALID_REQUEST` (HTTP 400). An unexpected server-side failure surfaces as `ERR_INTERNAL` (HTTP 500) in the same envelope.

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the range 1 to 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order, with ties broken by `id` ascending.

List endpoints additionally accept optional exact-match query parameters that filter the result set before pagination: `posture` on the Site list; `sample_class` on the DustSample list; `status` and `dust_sample_id` on the Collector list; `status` on the DHA, HousekeepingAudit, HotWorkPermit, Inspection, RetrofitProject, Incident, and CAPAAction lists; `current_posture` on the HousekeepingProgram list; `collector_id` on the HotWorkPermit, InspectionFinding, and Incident lists; `inspector_kind` on the Inspection list; `severity` on the InspectionFinding and Incident lists; `trigger_finding_id` on the RetrofitProject list; and `risk_tier` on the RetrofitLineItem list. A query parameter not listed here is ignored.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Site Posture as a Derived, System-Maintained Aggregate

Every Site carries a derived `posture` field taking one of four values — `COMPLIANT`, `CONDITIONAL`, `DEFICIENT`, or `STOP_WORK` — together with a derived numeric `posture_score` in the range 0 to 100. Neither field is ever set directly by a client. Instead, the server recomputes both whenever an event occurs that could shift the underlying risk picture: a new critical finding is filed, a housekeeping audit goes overdue, hot work starts or closes, a collector's venting is determined inadequate, an incident opens or closes, a retrofit project is approved, and so on.

The recompute algorithm has two stages. First, a score is computed by starting at 100 and subtracting integer penalties:

- 25 points for each open critical finding at the site, counting at most 2 such findings (so 0, 25, or 50 points deducted here),
- 10 points for each overdue housekeeping audit at the site, counting at most 3 such audits,
- 5 points for each hot-work permit currently `IN_PROGRESS` at the site, counting at most 3 such permits,
- 20 points if there exists at least one collector at the site with `status` equal to `IN_SERVICE` whose `vent_adequate` flag is false,
- 15 points if there exists at least one incident at the site whose `status` is `OPEN`, `INVESTIGATING`, or `CAPA_DEFINED`,
- 8 points if there exists at least one retrofit project at the site whose `status` is `APPROVED` or `IN_EXECUTION`.

The `posture_score` is then the result clamped so it never falls below 0.

Second, the numeric score is mapped to a posture band. The boundaries are inclusive of the higher band: a `posture_score` of at least 85 yields `COMPLIANT`; a score of at least 60 but below 85 yields `CONDITIONAL`; a score below 60 yields `DEFICIENT`. There is one override that ignores the score entirely: if the site carries 2 or more open critical findings, posture is forced to `STOP_WORK` regardless of what the numeric score would have produced. A site freshly created begins in `CONDITIONAL` posture.

### 2.5. Posture-Gated Operations

A site in `STOP_WORK` posture is barred from four operations: commissioning a collector, returning a collector to service, starting a hot-work permit, and starting execution on a retrofit project. In all four cases the rejection carries `ERR_POSTURE_STOP_WORK` (HTTP 409). This gate is what gives posture operational teeth — it converts a degrading compliance picture into a hard block on the activities most likely to introduce ignition sources or restart marginal equipment.

The gate is checked *after* authentication, authorization, path existence, and basic state-machine validity (so a request that would fail `ERR_INVALID_STATE` for an unrelated reason still surfaces that error rather than the posture gate). Posture checks run before any business-rule evaluation for the endpoint.

### 2.6. Common Resource Properties

Every entity in the system — Site, DustSample, Collector, DHA, HousekeepingProgram, HousekeepingAudit, HotWorkPermit, Inspection, InspectionFinding, RetrofitProject, RetrofitLineItem, Incident, and CAPAAction — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`) indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, updated whenever the resource's properties change.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by 1 on every mutation of the resource. This field powers optimistic concurrency control where a `concurrency_rules` entry applies.

Updates to derived fields — `posture`, `posture_score`, the counters, computed vent adequacy, computed risk scores — count as mutations and therefore refresh `updated_at` and increment `version` on the owning resource.

### 2.7. Numeric Precision and Rounding

The platform uses three distinct precision regimes, each pinned to the calculation that produces it:

- **Vent-area and reduced-pressure figures** (`required_vent_area_m2`, `pred_max_bar_g`) are rounded to exactly 3 decimal places using round-half-up.
- **Differential-pressure values** (`dp_current_inwc`, individual DP readings) are rounded to exactly 2 decimal places using round-half-up.
- **Composite scores** (`risk_score` on a DHA) are rounded to exactly 2 decimal places using round-half-up, with the rounding applied **per sub-component before summation** — that is, each per-dust sub-score and each per-collector sub-score is individually rounded to 2 decimal places before being added into the aggregate. The aggregate itself is not re-rounded.
- **Air-to-cloth ratio** (`air_to_cloth_ratio`) is rounded to exactly 4 decimal places using round-half-up.
- **Monetary contingency figures** on retrofit projects are integer cents; the rounding order is pinned (see §3.6) and no fractional cents ever appear.

These precision rules are normative; two implementations that disagree on the rounding order will produce observably different `risk_score` or `contingency_cents` values.

### 2.8. Optimistic Concurrency Control

Two write endpoints accept the current version of a parent entity and, when the client supplies it, reject the request when the supplied value has gone stale:

1. **Approving a DHA** accepts an `expected_site_version` in the request body. When the field is supplied, it must be an integer equal to the parent Site's current `version`; a non-integer value or a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). When the field is omitted, the check is skipped and the approval proceeds without an OCC comparison. Approving a DHA legitimately supersedes the previously approved DHA on the same site, mutates `last_dha_id`, and triggers a posture recompute — all of which bump `Site.version`. A stale expected version therefore indicates the client is acting on a superseded site snapshot.

2. **Finalizing a retrofit estimate** accepts an `expected_project_version` in the request body. When the field is supplied, it must be an integer equal to the parent RetrofitProject's current `version`; a non-integer value or a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). When the field is omitted, the check is skipped. Each line-item creation, update, or delete on the project legitimately mutates `estimated_cost_cents` and `contingency_cents` and bumps `RetrofitProject.version`. A stale expected version signals that the proposed totals were derived from a superseded estimate.

No other endpoint takes an expected-version field. Endpoints not listed here accept mutations without an OCC check.

### 2.9. Hierarchical Path Validation

For any endpoint whose URL contains multiple resource identifiers — for example `/api/sites/{id}/inspections/{inspection_id}/findings/{finding_id}/resolve` — the server validates each `{...}` segment **left to right**. The Site `id` is resolved first; if it does not exist the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any child segment is examined. The same rule applies to the child and grandchild segments in turn. The first unresolved segment short-circuits the request; subsequent segments are not consulted.

The same left-to-right rule applies when a request body carries optional foreign keys (such as `dust_sample_id`, `collector_id`, or `trigger_finding_id`): an unresolvable body-level reference is rejected with `ERR_NOT_FOUND` (HTTP 404) before state-machine or business-rule checks run.

### 2.10. Validation Ordering

When multiple validation rules apply to a single request, the server evaluates them in a fixed priority order so that the error returned is deterministic across implementations:

1. **Authentication first**: `X-User-Role` present and recognized; then `X-User-ID` present.
2. **Authorization next**: the role is permitted to invoke this endpoint at all.
3. **Path existence**: each `{id}` segment in the URL resolves (left-to-right).
4. **Input shape**: required fields present, scalar types correct (strings are strings, integers are integers — booleans are not accepted as numbers, numbers are not accepted as integers), enum values within declared sets, numeric ranges respected, and supplied ISO 8601 timestamps parseable; violations carry `ERR_INVALID_REQUEST` (HTTP 400). On the hot-work permit issuance endpoint specifically, the optional `collector_id` foreign key is resolved before the `valid_from`/`valid_to` timestamps are parsed; everywhere else, timestamp parsing is part of this step.
5. **Body foreign-key existence**: any optional foreign keys in the body (such as `dust_sample_id`, `collector_id`, or `trigger_finding_id`) resolve, else `ERR_NOT_FOUND` (HTTP 404).
6. **State-machine validity**: the target resource's current state allows the requested transition (else `ERR_INVALID_STATE`).
7. **Posture gate**: if the endpoint is one of the four posture-gated operations, the Site must not be in `STOP_WORK` (else `ERR_POSTURE_STOP_WORK`).
8. **Business safety rules**: vent adequacy at commission, filter-change-due at return-to-service, hot-work window active at start, fire watch elapsed at close, no permit overlap, combustible dust linked before DHA approval, segregation-of-duties constraints.
9. **Business constraint rules**: permit window length, fire-watch duration floor, audit due-ness, project non-empty, CAPA present, root cause known, no open CAPAs at incident close.
10. **Referential integrity**: trigger-finding state at retrofit approve/close, no open findings on a collector at decommission, no busy collector at take-out-of-service.
11. **Fiscal**: `total_projected_cents` does not exceed `scope_budget_cents` at finalize.
12. **OCC stale-version check**: when `expected_site_version` or `expected_project_version` is supplied, it matches the parent's current version.

The OCC check at step 12 runs only after every other validation has passed; an OCC rejection therefore always indicates the request was otherwise valid.

### 2.11. Logical Clock and System-Initiated Transitions

The server maintains a logical clock. At server start the clock reads `2026-05-01T00:00:00Z`. An administrative capability sets the clock to a supplied `to_iso8601` instant; this capability is restricted to `PlatformAdmin`. The supplied instant is applied verbatim — there is no monotonicity check, so the clock may be set to an earlier instant than its current reading. The endpoint responds `200 OK` with a data object carrying a single `current_utc` field echoing the new clock reading. Setting the clock triggers any system-initiated transitions whose preconditions have become true: HousekeepingAudits that should flip to `OVERDUE`, HotWorkPermits that should flip to `EXPIRED`, CAPAActions that should flip to `OVERDUE`, and any downstream recomputation of `HousekeepingProgram.current_posture`, DHA `overdue` flags, and `Site.posture` that those transitions imply.

All duration arithmetic ("24 hours", "180 days", "fire watch minutes") is measured against this logical clock, not against wall time.

## 3. Business Logic & Workflows

### 3.1. Site Bootstrap and the Meaning of Derived Counters

A `PlatformAdmin` registers a new facility by providing its `name`, `address`, `ahj_authority` label (the fire marshal or building department with jurisdiction), and `insurer_id` reference used for insurer-side audit access. The new Site is born in `CONDITIONAL` posture with `posture_score` initialized to 100 and all three derived counters at zero: `open_critical_findings` counts `InspectionFinding` rows at the site with status `OPEN` and severity `CRITICAL`; `open_overdue_housekeeping` counts `HousekeepingAudit` rows at the site with status `OVERDUE`; `hot_work_in_progress` counts `HotWorkPermit` rows at the site with status `IN_PROGRESS`. The `last_dha_id` field starts null and is populated the first time a DHA is approved on the site.

**Parent-linkage fields.** Every child entity carries a system-written foreign-key field naming its parent. DustSample, Collector, DHA, HousekeepingProgram, HotWorkPermit, Inspection, RetrofitProject, and Incident each carry a `site_id` field set by the server to the owning Site's `id`. HousekeepingAudit carries a `program_id` field referencing its parent HousekeepingProgram. InspectionFinding carries an `inspection_id` field referencing its parent Inspection. RetrofitLineItem carries a `project_id` field referencing its parent RetrofitProject. CAPAAction carries an `incident_id` field referencing its parent Incident. These fields are never supplied by the client on create — they are populated from the URL hierarchy — but they appear on the resource representation so clients can traverse upward.

An administrative `recompute_posture` action (restricted to `PlatformAdmin` and `ComplianceManager`) forces the site-posture derivation to run against the current counters; it refreshes `posture` and `posture_score`, refreshes `updated_at`, and increments the site's `version` by 1. This is the only client-invoked way to recompute posture; every other recompute is a side effect of a workflow transition described below.

A `ComplianceManager` may additionally update a Site's `name`, `address`, `ahj_authority`, or `insurer_id` via the site-modification endpoint; only fields present and non-null in the request body are written, `Site.version` increments by 1 only when at least one field is actually written, and such updates do not by themselves trigger a posture recompute (the inputs are not posture-relevant). Changing `insurer_id` does not retroactively reclassify existing DustSamples or re-run existing retrofit contingency calculations; the insurer-conservative variants apply only at the moment each classification or contingency calculation is executed.

### 3.2. Registering Dust Samples and Kst Classification

A `ComplianceEngineer` registers a dust sample by supplying the `material_name`, the Kst value `kst_bar_m_per_s` in bar·m/s (a non-negative number; zero means non-combustible), the maximum explosion pressure `pmax_bar_g` in bar-g (strictly positive), the minimum ignition energy `mie_mj` in millijoules (strictly positive), and an external `lab_report_ref` reference string. On creation, and on every subsequent update to any of these fields, the server derives two fields:

- `sample_class`: `ST0` when `kst_bar_m_per_s` is exactly zero; `ST1` when `kst_bar_m_per_s` is greater than zero and at most 200; `ST2` when `kst_bar_m_per_s` is greater than 200 and at most 300; `ST3` when `kst_bar_m_per_s` exceeds 300. Boundary values belong to the lower band (the comparisons are inclusive at the upper edge of each band).
- `combustible`: true exactly when `kst_bar_m_per_s` is greater than zero.

There is one **insurer-conservative variant** of this classification. When the owning Site's `insurer_id` begins with the literal prefix `IC-`, the bands tighten: `ST1` applies when `kst_bar_m_per_s` is greater than zero and at most 150; `ST2` applies when `kst_bar_m_per_s` is greater than 150 and at most 250; `ST3` applies when `kst_bar_m_per_s` exceeds 250. The same dust sample, registered under a conservative-insurer site, can therefore be classified one band higher than it would be under the default NFPA bands.

The classification feeds every downstream consumer. When a DustSample's Kst value changes, the server must (a) recompute the explosion-protection design on every Collector that references this sample via `dust_sample_id`, and (b) recompute the Kst rollup and risk score on every DHA that links this sample.

### 3.3. Collector Engineering: Design, Commissioning, and Service

A Collector represents one dust-collection unit at a site. A `ComplianceEngineer` creates it by supplying the equipment `tag` (e.g., `DC-101`), a `dust_sample_id` reference to the worst-case dust this collector serves, the `design_airflow_acfm` in actual cubic feet per minute (strictly positive integer), the net `filter_area_ft2` in square feet (strictly positive), and the dirty-side `internal_volume_m3` in cubic meters (strictly positive). The client may optionally supply `installed_vent_area_m2` (non-negative; defaults to 0 when omitted).

On creation and on every update to airflow, filter area, internal volume, installed vent area, or the linked dust sample, the server runs the **explosion-protection design calculation**:

1. Pull `Kst` from the linked dust sample's `kst_bar_m_per_s` and `Pmax` from the linked dust sample's `pmax_bar_g`.
2. The static activation pressure `Pstat` is 0.1 bar-g (a fixed constant).
3. Compute the maximum reduced pressure as `Pred_max = min(Pmax * 0.5, 0.5 + 0.04 * Kst**0.5)` — that is, take the smaller of (half of Pmax) and (0.5 plus 0.04 multiplied by the square root of Kst).
4. Compute the unrestricted vent coefficient `Av0 = 0.1 * Kst * V**(2.0/3.0)`, where `V` is `internal_volume_m3` raised to the two-thirds power.
5. The required vent area is `required_vent_area_m2 = Av0 * (Pmax / max(Pred_max, 0.05))**0.5` — Av0 multiplied by the square root of (Pmax divided by the larger of Pred_max and 0.05). The floor of 0.05 on the denominator prevents degenerate vent sizing when Pred_max approaches zero.
6. Round `required_vent_area_m2` to exactly 3 decimal places, round-half-up.
7. Record `pred_max_bar_g` equal to `Pred_max`, also rounded to exactly 3 decimal places, round-half-up.

There is a **performance-based variant** for large vessels. When `internal_volume_m3` exceeds 25, a 1.20 safety multiplier is applied to `required_vent_area_m2` before the 3-decimal-place rounding — so the same collector geometry yields a larger required vent area under the variant.

The server then derives the **vent adequacy** flag: `vent_adequate` is true exactly when `installed_vent_area_m2` is greater than or equal to `required_vent_area_m2`. A collector whose installed venting falls short of the requirement cannot be commissioned.

A collector is also continuously monitored for differential pressure. Each submission of a `dp_inwc` reading (a `ComplianceEngineer` or `HousekeepingAuditor` may submit one) stores the reading rounded to exactly 2 decimal places round-half-up, updates `dp_current_inwc` to that rounded value, refreshes `updated_at`, and increments `Collector.version` by 1; the `201` response carries the updated Collector object (not a separate reading resource). The trend derivation looks at the last 5 readings on the collector, including the current one, ordered by `created_at` ascending (ties broken by the server-minted reading sequence):

- If `dp_current_inwc` is at least 6.0 inches of water column (the high-alarm threshold), `dp_trend` is `ALARM_HIGH`.
- Else if there are at least 3 readings in the lookback window and the most recent reading minus the reading three positions back is at least 1.5 inches of water column, `dp_trend` is `RISING`.
- Otherwise `dp_trend` is `STABLE`.

A filter change becomes due when either condition holds: `dp_current_inwc` is at least 6.0 in w.c., OR at least 180 days have elapsed since `last_filter_change_at`. In either case `filter_change_due` is set true. Recording a filter change resets `last_filter_change_at` to the current clock, resets `dp_current_inwc` to 0, clears `filter_change_due` to false, and bumps `Collector.version` by 1. The `dp_trend` flag is then re-derived from the retained reading window by the usual trend rule, so after a filter change `dp_trend` reflects the stored readings (it may be `RISING` even though `dp_current_inwc` is 0).

The derived `air_to_cloth_ratio` is the `design_airflow_acfm` divided by `filter_area_ft2`, rounded to 4 decimal places, round-half-up. It is recomputed whenever airflow or filter area changes.

**Collector lifecycle.** A new collector starts in `DRAFT`. Commissioning it — a `ComplianceEngineer` action — moves it to `IN_SERVICE`. Commissioning requires three preconditions, evaluated in the order imposed by §2.10 (posture gate before business safety rules): the owning Site must not be in `STOP_WORK` posture (else `ERR_POSTURE_STOP_WORK`, HTTP 409); the collector's `vent_adequate` must be true (else `ERR_VENT_UNDERSIZED`, HTTP 422); and the dust sample referenced by `dust_sample_id` must exist and must be combustible (a non-combustible linked sample is rejected with `ERR_INVALID_STATE`, HTTP 409). Successful commissioning recomputes the site's posture and increments the site's `version` by 1.

Taking a collector out of service — also a `ComplianceEngineer` action — moves it from `IN_SERVICE` to `OUT_OF_SERVICE`. The transition is refused with `ERR_COLLECTOR_BUSY` (HTTP 422) when any `HotWorkPermit` whose `collector_id` equals this collector is currently in `ISSUED` or `IN_PROGRESS` status. When the transition succeeds *and* `filter_change_due` is true at the moment of the transition, the system auto-creates an `InspectionFinding` of severity `MAJOR` on the most recently created Inspection at the site that is in `OPEN` or `SUBMITTED` status; if no such inspection exists, the system first creates a new Inspection in `OPEN` status (with `inspector_kind` `INTERNAL` and `inspector_ref` `"system"`) and then attaches the finding to it. Auto-created findings — here and everywhere else the system files one — carry `due_at` equal to the current clock reading and start in `OPEN` status. In either path the transition also recomputes the site's posture and increments the site's `version` by 1.

Returning a collector to service — again a `ComplianceEngineer` action — moves it from `OUT_OF_SERVICE` back to `IN_SERVICE`. The transition requires `filter_change_due` to be false (else `ERR_FILTER_CHANGE_REQUIRED`, HTTP 422) and the Site not to be in `STOP_WORK` (else `ERR_POSTURE_STOP_WORK`, HTTP 409). The side effect is a posture recompute.

Decommissioning is reserved for `ComplianceManager` and moves the collector from `OUT_OF_SERVICE` to the terminal `DECOMMISSIONED` state. The transition is refused with `ERR_COLLECTOR_HAS_OPEN_FINDING` (HTTP 422) when any `InspectionFinding` referencing this collector is in `OPEN` or `IN_PROGRESS` status. Successful decommissioning recomputes posture.

### 3.4. The Dust Hazard Analysis: Authoring, Approval, and Supersession

The DHA is the central compliance document NFPA 652 demands. A `ComplianceEngineer` authors one by supplying a `title` and their own `author_id` (the value of the acting `X-User-ID` header). The new DHA starts in `DRAFT`. Any `ComplianceEngineer` can link and unlink dust samples to it, in any DHA status (the endpoints perform no state or author check): linking identifies a DustSample as part of the hazard inventory this DHA covers, and each link or unlink triggers recomputation of two derived fields. Linking an already-linked sample, or unlinking a sample that is not linked, is idempotent — the operation succeeds with no change to the link set, though the derived fields are still recomputed and the DHA's `version` still increments.

The first derived field, `kst_class_highest`, is the maximum Kst class over the linked samples that are combustible. Samples are ranked `ST0` < `ST1` < `ST2` < `ST3`; the highest-ranked class among combustible linked samples wins. If no linked sample is combustible (or no samples are linked at all), `kst_class_highest` is `ST0`.

The second derived field, `risk_score`, is a 0-to-100 weighted composite computed as follows:

- **Dust sub-total**: for each linked combustible DustSample, compute a per-dust sub-score of `rank(sample_class) * 8 + max(0, 10 - mie_mj)` — where `rank` maps `ST0` to 0, `ST1` to 1, `ST2` to 2, `ST3` to 3 — then round each per-dust sub-score to 2 decimal places, round-half-up. Sum the rounded per-dust values.
- **Collector sub-score**: for each Collector at the same Site whose `status` is `IN_SERVICE`, compute a per-collector sub-score of `3 if filter_change_due else 0, plus 5 if dp_trend is ALARM_HIGH else 0, plus 3 if dp_trend is RISING else 0, plus 0 if vent_adequate else 12`. Round each per-collector sub-score to 2 decimal places, round-half-up. Sum the rounded per-collector values.
- **Finding sub-score**: 6 points per open critical finding at the site plus 2 points per overdue housekeeping audit at the site (using the Site's derived counters).
- **Hot-work sub-score**: 4 points per hot-work permit currently in progress at the site.

The `raw` score is the sum of the four sub-scores, with no further rounding; the published `risk_score` is `min(100, raw)`. The per-dust and per-collector rounding order is normative — rounding only at the end would produce different values.

Both `kst_class_highest` and `risk_score` are stored values, recomputed only when the DHA is created, when a dust sample is linked or unlinked, and when an update to a linked DustSample triggers the cascade described in §3.2; later changes to the inputs of the collector, finding, and hot-work sub-scores (DP readings, `dp_trend` or `filter_change_due` changes, collector status transitions, or changes to the site's derived counters) do not by themselves recompute a DHA's stored `risk_score`.

When the author is satisfied with the draft, they submit it; submission moves the DHA from `DRAFT` to `SUBMITTED`. Submission requires that the acting `X-User-ID` equal the DHA's `author_id`; a mismatch is rejected with `ERR_SOD_VIOLATION` (HTTP 422).

Approval is reserved for `ComplianceManager`. The request may carry `expected_site_version` per §2.8 — when supplied, a mismatch against the Site's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Two further preconditions apply, and the OCC check is the last of all validations to run: the approver must not be the DHA's author (a `ComplianceManager` whose `X-User-ID` equals `author_id` is rejected with `ERR_SOD_VIOLATION`, HTTP 422), and at least one linked DustSample must be combustible — equivalently, `kst_class_highest` must not be `ST0` because at least one combustible dust must be referenced (else `ERR_NO_COMBUSTIBLE_DUST`, HTTP 422).

A successful approval writes `approver_id` to the acting `X-User-ID`, sets `review_due_at` to the approval timestamp plus the review period (see §3.4.1 below), writes this DHA's `id` into `Site.last_dha_id`, transitions any *other* DHA on the same site currently in `APPROVED` state to `SUPERSEDED`, recomputes the site posture, and increments the site's `version` by 1.

Rejection is also a `ComplianceManager` action and moves the DHA from `SUBMITTED` to `REJECTED`. The author can then revise it back to `DRAFT` — the revision transition requires the acting `X-User-ID` to equal the DHA's `author_id` (a mismatch is rejected with `ERR_SOD_VIOLATION`, HTTP 422) — and iterate again through submit and approve.

**3.4.1 Review scheduling.** Each approved DHA carries a `review_due_at` field set at approval time to the approval timestamp plus `REVIEW_PERIOD_DAYS` days, where `REVIEW_PERIOD_DAYS` is 365. A DHA whose `review_due_at` is in the past relative to the current clock has its `overdue` flag set to true; otherwise `overdue` is false. This flag is recomputed whenever the clock advances. Approval also resets `overdue` to false.

### 3.5. Housekeeping Programs and Audit Cadence

A `ComplianceEngineer` or `ComplianceManager` establishes a HousekeepingProgram for a site by supplying a program `name`, a `target_accumulation_g_per_m2` ceiling in grams per square meter (strictly positive), and a `frequency_hours` interval in hours (strictly positive integer). The server records the acting `X-User-ID` onto the program's `created_by` field at creation. The program tracks `last_audit_at` (null until the first audit completes) and derives `next_due_at` as `last_audit_at + frequency_hours` hours (null until the first audit).

The program's `current_posture` is derived continuously:

- If `last_audit_at` is null — the program has never been audited — `current_posture` is `OVERDUE` (a never-audited program is non-compliant by definition) and `next_due_at` remains null.
- Else if the current clock is strictly later than `next_due_at`, `current_posture` is `OVERDUE`.
- Else if the current clock is strictly later than `next_due_at` minus 24 hours, `current_posture` is `DUE_SOON`.
- Otherwise `current_posture` is `CURRENT`.

Both comparisons are strict; an instant exactly equal to `next_due_at` is not yet overdue.

A `HousekeepingAuditor` schedules an audit by supplying their own `auditor_id`, the `measured_accumulation_g_per_m2` they expect to record (non-negative), and a `scheduled_for` timestamp. At creation the system snapshots the program's current `target_accumulation_g_per_m2` into the audit's `pass_threshold_g_per_m2` field — so a later change to the program target does not retroactively alter the pass criterion for an audit already on the books. The new audit starts in `SCHEDULED` status, with `executed_at` null.

Recording an audit result is the auditor's own action — the acting `X-User-ID` must equal `auditor_id` (a mismatch is rejected with `ERR_SOD_VIOLATION`, HTTP 422). The transition from `SCHEDULED` to `RECORDED` requires that `scheduled_for` is not in the future relative to the current clock; an audit whose scheduled time has not yet arrived is rejected with `ERR_AUDIT_NOT_DUE` (HTTP 422). The not-yet-due check applies only on the `SCHEDULED → RECORDED` path; an audit in `OVERDUE` may be recorded regardless of its `scheduled_for`. On record, the server stamps `executed_at` with the current clock, computes `pass` as true exactly when `measured_accumulation_g_per_m2` is less than or equal to `pass_threshold_g_per_m2`, writes `executed_at` into the program's `last_audit_at`, recomputes `next_due_at` as `executed_at + frequency_hours` hours, and recomputes both the program's `current_posture` and the owning Site's `posture`. When `pass` is false the server additionally auto-creates an `InspectionFinding` of severity `MAJOR` on the most recent `OPEN` or `SUBMITTED` Inspection at the site (creating a new `OPEN` Inspection first if none exists). Successful recording increments the site's `version` by 1.

When the current clock advances past `scheduled_for + frequency_hours` hours and the audit is still in `SCHEDULED`, the system auto-transitions the audit to `OVERDUE`. This transition increments the Site's `open_overdue_housekeeping` counter by 1 and recomputes the site posture. An overdue audit is not lost — the auditor may still record it later, transitioning `OVERDUE → RECORDED`. That recovery path applies the same side effects as the direct `SCHEDULED → RECORDED` transition, plus a decrement of `open_overdue_housekeeping` by 1 and a further posture recompute.

An auditor may also skip an audit entirely (transition `SCHEDULED → SKIPPED`), again requiring the acting `X-User-ID` to equal the audit's `auditor_id` (else `ERR_SOD_VIOLATION`, HTTP 422); an audit in terminal `SKIPPED` status is excluded from the schedule derivation altogether and has no further effect.

No creator-versus-auditor segregation-of-duties check is enforced for housekeeping: the only identity rules on these endpoints are the auditor-ownership checks above. The program's `created_by` field is recorded for traceability but is not consulted by any validation.

### 3.6. Hot-Work Permits and Fire Watch

A `SafetyManager` issues a hot-work permit by supplying `work_description`, their own `issuer_id`, the `performer_id` of the `HotWorkPerformer` who will execute the work (issuance performs no comparison between `performer_id` and `issuer_id` — the two may be equal; segregation between issuer and performer is enforced only through the transition-level identity checks below), an optional `collector_id` when the work is on or near a specific collector, a `valid_from` timestamp marking the inclusive start of the permit window, a `valid_to` timestamp marking the exclusive end (the window is half-open: `[valid_from, valid_to)`), and `fire_watch_minutes_after` — the post-work fire-watch duration in minutes, which NFPA 51B requires to be at least 30.

Two issuance-time constraints apply. The window itself must be well-formed: `valid_to` must be strictly later than `valid_from`, and `valid_to` must not exceed `valid_from` plus 24 hours; a malformed window is rejected with `ERR_PERMIT_WINDOW_INVALID` (HTTP 422). The fire-watch duration must be at least 30 minutes; a shorter value is rejected with `ERR_FIRE_WATCH_TOO_SHORT` (HTTP 422).

A new permit starts in `ISSUED`. The performer starts work by transitioning `ISSUED → IN_PROGRESS`. The acting `X-User-ID` must equal the permit's `performer_id` (a mismatch is rejected with `ERR_SOD_VIOLATION`, HTTP 422). Three further preconditions apply: the owning Site must not be in `STOP_WORK` (else `ERR_POSTURE_STOP_WORK`, HTTP 409); the current clock must lie within `[valid_from, valid_to)` — that is, greater than or equal to `valid_from` and strictly earlier than `valid_to` (else `ERR_PERMIT_WINDOW_INACTIVE`, HTTP 422); and no *other* HotWorkPermit on the same Site may already be in `IN_PROGRESS` with a window overlapping this one's (else `ERR_PERMIT_OVERLAP`, HTTP 422). When the permit references a collector via `collector_id`, that collector's `status` must be `IN_SERVICE` or `OUT_OF_SERVICE` — a `DECOMMISSIONED` collector is rejected with `ERR_INVALID_STATE` (HTTP 409). A successful start increments the Site's `hot_work_in_progress` counter by 1, recomputes posture, and increments the Site's `version` by 1.

Closing a permit — again a performer action requiring `X-User-ID` equal to `performer_id` (else `ERR_SOD_VIOLATION`, HTTP 422) — moves it from `IN_PROGRESS` to `CLOSED`. The transition requires that the current clock be at or past `valid_to` plus `fire_watch_minutes_after` minutes; a close attempted earlier is rejected with `ERR_FIRE_WATCH_INCOMPLETE` (HTTP 422). On close the Site's `hot_work_in_progress` decrements by 1 and posture is recomputed.

A `SafetyManager` may void a permit before it starts; voiding moves `ISSUED → VOIDED` and requires the acting `X-User-ID` to equal the permit's `issuer_id` (else `ERR_SOD_VIOLATION`, HTTP 422). The terminal `VOIDED` status records that the permit was cancelled administratively rather than executed or expired.

Finally, when the current clock advances past `valid_to` while the permit is still `ISSUED` (never started), the system auto-transitions the permit to `EXPIRED`. Expiry auto-creates an `InspectionFinding` of severity `MINOR` on the most recent `OPEN` or `SUBMITTED` Inspection at the site (creating one if necessary) and recomputes posture.

### 3.7. Inspections and Findings

An `InspectorUser` files an inspection by supplying `inspector_kind` (`AHJ`, `INSURER`, or `INTERNAL`), an external `inspector_ref` reference string, and the `conducted_at` timestamp of the walkdown. The new inspection starts in `OPEN`. The inspector then adds findings, each carrying an optional `collector_id` (set when the finding is collector-specific), a `severity` of `OBSERVATION`, `MINOR`, `MAJOR`, or `CRITICAL`, a free-text `description`, and a `due_at` correct-by date.

Each finding starts in `OPEN`. When a finding of severity `CRITICAL` is created, the owning Site's `open_critical_findings` counter increments by 1 and the site's `version` increments by 1; posture is recomputed.

The inspector submits the inspection when findings are complete; the transition `OPEN → SUBMITTED` has no preconditions. A `ComplianceManager` then either accepts or rejects the submission. Acceptance (`SUBMITTED → ACCEPTED`) requires that every finding on the inspection is in `VERIFIED` or `WITHDRAWN` status; any other finding state blocks acceptance with `ERR_INVALID_STATE` (HTTP 409). The terminal `ACCEPTED` status marks the inspection as closed-out with all findings resolved. Rejection (`SUBMITTED → REJECTED`) cascades: every finding on the inspection currently in `OPEN` or `IN_PROGRESS` status transitions to `DISPUTED`; the cascade decrements `open_critical_findings` by 1 for each cascaded finding that is `CRITICAL` and was `OPEN` (a `CRITICAL` finding cascaded from `IN_PROGRESS` does not decrement the counter). Both acceptance and rejection recompute posture.

Findings themselves have a lifecycle. A `ComplianceEngineer` starts work on a finding (`OPEN → IN_PROGRESS`, or from `REOPENED → IN_PROGRESS` on the rework path). The engineer resolves it (`IN_PROGRESS → RESOLVED`); when severity is `CRITICAL` this decrements `open_critical_findings` by 1 and recomputes posture. A `ComplianceManager` verifies the resolution (`RESOLVED → VERIFIED`); verification is modeled as the `ComplianceManager` standing in for the inspector's sign-off. The manager may instead reopen the finding (`RESOLVED → REOPENED`); for a `CRITICAL` finding this increments `open_critical_findings` by 1 and recomputes posture. A `ComplianceEngineer` may dispute a finding outright (`OPEN → DISPUTED`); for a `CRITICAL` finding this decrements `open_critical_findings` by 1 and recomputes posture. Finally, the `InspectorUser` withdraws a disputed finding (`DISPUTED → WITHDRAWN`), which is terminal.

### 3.8. Retrofit Projects and Tiered Contingency

A `ComplianceEngineer` scopes a retrofit project in response to a critical inspection finding by supplying a `name`, the `trigger_finding_id` referencing the driving `CRITICAL` InspectionFinding, and a `scope_budget_cents` integer budget (strictly positive). At scoping time the only requirement on `trigger_finding_id` is that it resolves to an existing InspectionFinding belonging to an Inspection at the same site (else `ERR_NOT_FOUND`, HTTP 404); the severity-and-status requirement on the trigger finding is enforced later, at approval time. The new project starts in `SCOPING`, with `estimated_cost_cents`, `contingency_cents`, `total_projected_cents`, and `contingency_rounding_cents` all initialized to 0.

The engineer then builds up line items. Each line item carries a `description`, a `cost_cents` integer (strictly positive), and a `risk_tier` of `LOW`, `MEDIUM`, or `HIGH`. Line items may be created, updated, and deleted regardless of the parent project's status — the line-item endpoints perform no project state check. Creating, updating, or deleting a line item triggers the **retrofit contingency calculation**, which maintains four derived totals on the parent project:

1. `estimated_cost_cents` is the sum of `cost_cents` across all line items (no status filter — line items are unstate-machined).
2. Each line item contributes a per-line contingency at a tier-specific rate: 5 percent of `cost_cents` for `LOW`, 12 percent for `MEDIUM`, 22 percent for `HIGH`. Each per-line contingency is rounded to the nearest cent, round-half-up, **before** summing.
3. `contingency_cents` is the sum of those per-line rounded contingencies.
4. `contingency_rounding_cents` is the reconciliation remainder, defined as `(estimated_cost_cents + contingency_cents) − (estimated_cost_cents + contingency_cents_gross)` where `contingency_cents_gross` is the same sum of per-line rounded contingencies. Under the current scheme this remainder is always 0; the field exists so a future change in rounding order (for example, sum-then-round) surfaces drift explicitly.
5. `total_projected_cents` is `estimated_cost_cents + contingency_cents`.

There is an **insurer-mandated reporting variant**. When the owning Site's `insurer_id` begins with the literal prefix `IC-`, the rounding order changes: per-line contingencies are summed *unrounded* and the total is rounded once to cents at the end. For projects with two or more line items this variant can produce a different `contingency_cents` than the default per-line-then-sum order.

Every line-item mutation also increments the parent RetrofitProject's `version` by 1, so a client holding a stale snapshot of the project will be detected at finalize time.

Finalizing the estimate — a `ComplianceEngineer` action — moves the project from `SCOPING` to `ESTIMATED`. The request may carry `expected_project_version`; when supplied it must match the project's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). Two further preconditions apply: the project must have at least one line item (else `ERR_PROJECT_EMPTY`, HTTP 422), and `total_projected_cents` must not exceed `scope_budget_cents` (else `ERR_BUDGET_EXCEEDED`, HTTP 422). A successful finalize re-runs the contingency calculation to pin the totals.

Approving the project — a `ComplianceManager` action — moves it from `ESTIMATED` to `APPROVED`. The `trigger_finding_id` must reference an InspectionFinding with severity `CRITICAL` whose current status is `OPEN`, `IN_PROGRESS`, or `RESOLVED`; any other status is rejected with `ERR_TRIGGER_FINDING_INVALID` (HTTP 422). On approval, if the trigger finding is currently `OPEN`, it transitions to `IN_PROGRESS`. Approval also recomputes posture.

Starting execution — a `ComplianceEngineer` action — moves the project from `APPROVED` to `IN_EXECUTION`. This is one of the four posture-gated operations: the Site must not be in `STOP_WORK` (else `ERR_POSTURE_STOP_WORK`, HTTP 409).

Closing the project — a `ComplianceManager` action — moves it from `IN_EXECUTION` to `CLOSED`. The trigger finding must be in `VERIFIED` status; any other status is rejected with `ERR_TRIGGER_FINDING_OPEN` (HTTP 422). Closing recomputes posture.

A `ComplianceManager` may cancel a project at any point while it is `SCOPING` or `ESTIMATED`; the transition lands the project in the terminal `CANCELLED` status.

### 3.9. Incident Investigation and CAPA

A `ComplianceManager` or `SafetyManager` declares an incident by supplying `occurred_at`, an optional `collector_id` for collector-involved incidents, a `kind` of `FIRE`, `DEFLAGRATION`, `EMBER_RELEASE`, or `NEAR_MISS`, a free-text `description`, a `severity` of `MINOR`, `MAJOR`, or `CATASTROPHIC`, a `root_cause_code` of `HOUSEKEEPING`, `HOT_WORK`, `EQUIPMENT_FAILURE`, `STATIC_DISCHARGE`, or `UNKNOWN`, and an `investigation_lead_id` identifying the `IncidentInvestigator` who will lead the inquiry. The new incident starts in `OPEN`, with `capa_count` and `capa_open_count` both at 0. Declaration recomputes posture and increments the Site's `version` by 1.

Starting the investigation — an `IncidentInvestigator` action — moves the incident from `OPEN` to `INVESTIGATING`. The acting `X-User-ID` must equal `investigation_lead_id`. Segregation of duties applies here too: the `investigation_lead_id` must differ from any HotWorkPermit's `issuer_id` where that permit's `collector_id` equals the incident's `collector_id` and the permit's window contains `occurred_at` — a violation is rejected with `ERR_SOD_VIOLATION` (HTTP 422).

During investigation the lead authors CAPA actions; any `IncidentInvestigator` may author one, and the create endpoint performs no incident-status or lead-identity check (the incident merely has to exist). Each CAPAAction carries a `description`, an `owner_id` for the action owner, and a `due_at` date. Creating one increments the incident's `capa_count` and `capa_open_count` by 1 and increments the incident's `version` by 1. An action starts in `OPEN`; the owner (acting `X-User-ID` equal to `owner_id`, else `ERR_SOD_VIOLATION`, HTTP 422 — and note the endpoint is authorized for `IncidentInvestigator` only, so the recorded `owner_id` must be an identifier the client uses with that role) starts it (`OPEN → IN_PROGRESS`) and later closes it (`IN_PROGRESS → CLOSED`), which sets `closed_at` to the current clock, decrements `capa_open_count` by 1, and recomputes posture. When the clock advances past `due_at` while an action is `OPEN` or `IN_PROGRESS`, the system auto-transitions it to `OVERDUE` and recomputes posture. An overdue action can still be closed by its owner (`OVERDUE → CLOSED`), with the same side effects as the on-time close path.

Once investigation has produced at least one CAPA action and the root cause is known, the lead defines CAPA — moving the incident from `INVESTIGATING` to `CAPA_DEFINED`. The transition requires at least one CAPAAction (else `ERR_CAPA_REQUIRED`, HTTP 422) and requires `root_cause_code` to differ from `UNKNOWN` (else `ERR_ROOT_CAUSE_REQUIRED`, HTTP 422).

A `ComplianceManager` closes the incident (`CAPA_DEFINED → CLOSED`) once every CAPA action is closed: the transition requires `capa_open_count` to equal zero (else `ERR_CAPA_OPEN`, HTTP 422). Closing recomputes posture. A closed incident can be reopened (`CLOSED → REOPENED`) by a `ComplianceManager`; reopening also recomputes the site's posture and increments the site's `version` by 1. The investigator can resume investigation from `REOPENED` (transition back to `INVESTIGATING`) provided the acting `X-User-ID` still equals `investigation_lead_id`.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (a Site, a DustSample, a Collector, a DHA, a HousekeepingProgram, a HousekeepingAudit, a HotWorkPermit, an Inspection, an InspectionFinding, a RetrofitProject, a RetrofitLineItem, an Incident, a CAPAAction, a DP reading) return a `201 Created` status code. Operations that modify an existing resource, transition a resource's state, or return a resource without creating a new one return a `200 OK` status code. Deleting a line item returns `204 No Content`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/api/sites` | Create a new Site | PlatformAdmin |
| GET    | `/api/sites` | List Sites | PlatformAdmin, ComplianceManager, ComplianceEngineer, SafetyManager, HousekeepingAuditor, IncidentInvestigator, InspectorUser |
| GET    | `/api/sites/{id}` | Get a specific Site | PlatformAdmin, ComplianceManager, ComplianceEngineer, SafetyManager, HousekeepingAuditor, IncidentInvestigator, InspectorUser |
| PATCH  | `/api/sites/{id}` | Update a Site's profile fields | PlatformAdmin, ComplianceManager |
| POST   | `/api/sites/{id}/recompute_posture` | Force a posture recompute on a Site | PlatformAdmin, ComplianceManager |
| POST   | `/api/sites/{id}/dust-samples` | Register a new DustSample | ComplianceEngineer |
| GET    | `/api/sites/{id}/dust-samples` | List DustSamples at a Site | ComplianceEngineer, ComplianceManager, InspectorUser |
| GET    | `/api/sites/{id}/dust-samples/{sample_id}` | Get a specific DustSample | ComplianceEngineer, ComplianceManager, InspectorUser |
| PATCH  | `/api/sites/{id}/dust-samples/{sample_id}` | Update a DustSample | ComplianceEngineer |
| POST   | `/api/sites/{id}/collectors` | Register a new Collector | ComplianceEngineer |
| GET    | `/api/sites/{id}/collectors` | List Collectors at a Site | ComplianceEngineer, ComplianceManager, InspectorUser, SafetyManager |
| GET    | `/api/sites/{id}/collectors/{collector_id}` | Get a specific Collector | ComplianceEngineer, ComplianceManager, InspectorUser, SafetyManager |
| PATCH  | `/api/sites/{id}/collectors/{collector_id}` | Update a Collector | ComplianceEngineer |
| POST   | `/api/sites/{id}/collectors/{collector_id}/commission` | Commission a Collector | ComplianceEngineer |
| POST   | `/api/sites/{id}/collectors/{collector_id}/take_out_of_service` | Take a Collector out of service | ComplianceEngineer |
| POST   | `/api/sites/{id}/collectors/{collector_id}/return_to_service` | Return a Collector to service | ComplianceEngineer |
| POST   | `/api/sites/{id}/collectors/{collector_id}/decommission` | Decommission a Collector | ComplianceManager |
| POST   | `/api/sites/{id}/collectors/{collector_id}/dp-readings` | Submit a differential-pressure reading | ComplianceEngineer, HousekeepingAuditor |
| POST   | `/api/sites/{id}/collectors/{collector_id}/record_filter_change` | Record a filter change | ComplianceEngineer |
| POST   | `/api/sites/{id}/dhas` | Author a new DHA | ComplianceEngineer |
| GET    | `/api/sites/{id}/dhas` | List DHAs at a Site | ComplianceEngineer, ComplianceManager, InspectorUser |
| GET    | `/api/sites/{id}/dhas/{dha_id}` | Get a specific DHA | ComplianceEngineer, ComplianceManager, InspectorUser |
| POST   | `/api/sites/{id}/dhas/{dha_id}/samples/{sample_id}` | Link a DustSample to a DHA | ComplianceEngineer |
| DELETE | `/api/sites/{id}/dhas/{dha_id}/samples/{sample_id}` | Unlink a DustSample from a DHA | ComplianceEngineer |
| POST   | `/api/sites/{id}/dhas/{dha_id}/submit` | Submit a DHA for approval | ComplianceEngineer |
| POST   | `/api/sites/{id}/dhas/{dha_id}/approve` | Approve a DHA | ComplianceManager |
| POST   | `/api/sites/{id}/dhas/{dha_id}/reject` | Reject a DHA | ComplianceManager |
| POST   | `/api/sites/{id}/dhas/{dha_id}/revise` | Return a rejected DHA to draft | ComplianceEngineer |
| POST   | `/api/sites/{id}/housekeeping-programs` | Create a HousekeepingProgram | ComplianceEngineer, ComplianceManager |
| GET    | `/api/sites/{id}/housekeeping-programs` | List HousekeepingPrograms at a Site | ComplianceEngineer, ComplianceManager, HousekeepingAuditor, InspectorUser |
| GET    | `/api/sites/{id}/housekeeping-programs/{program_id}` | Get a specific HousekeepingProgram | ComplianceEngineer, ComplianceManager, HousekeepingAuditor, InspectorUser |
| POST   | `/api/sites/{id}/housekeeping-programs/{program_id}/audits` | Schedule a HousekeepingAudit | HousekeepingAuditor |
| GET    | `/api/sites/{id}/housekeeping-programs/{program_id}/audits` | List audits under a program | ComplianceEngineer, ComplianceManager, HousekeepingAuditor, InspectorUser |
| GET    | `/api/sites/{id}/housekeeping-programs/{program_id}/audits/{audit_id}` | Get a specific HousekeepingAudit | ComplianceEngineer, ComplianceManager, HousekeepingAuditor, InspectorUser |
| POST   | `/api/sites/{id}/housekeeping-programs/{program_id}/audits/{audit_id}/record` | Record a HousekeepingAudit result | HousekeepingAuditor |
| POST   | `/api/sites/{id}/housekeeping-programs/{program_id}/audits/{audit_id}/skip` | Skip a scheduled audit | HousekeepingAuditor |
| POST   | `/api/sites/{id}/hot-work-permits` | Issue a HotWorkPermit | SafetyManager |
| GET    | `/api/sites/{id}/hot-work-permits` | List HotWorkPermits at a Site | SafetyManager, ComplianceManager, ComplianceEngineer, HotWorkPerformer, InspectorUser |
| GET    | `/api/sites/{id}/hot-work-permits/{permit_id}` | Get a specific HotWorkPermit | SafetyManager, ComplianceManager, ComplianceEngineer, HotWorkPerformer, InspectorUser |
| POST   | `/api/sites/{id}/hot-work-permits/{permit_id}/start` | Start work under a permit | HotWorkPerformer |
| POST   | `/api/sites/{id}/hot-work-permits/{permit_id}/close` | Close a permit after fire watch | HotWorkPerformer |
| POST   | `/api/sites/{id}/hot-work-permits/{permit_id}/void` | Void a permit before work starts | SafetyManager |
| POST   | `/api/sites/{id}/inspections` | File a new Inspection | InspectorUser |
| GET    | `/api/sites/{id}/inspections` | List Inspections at a Site | InspectorUser, ComplianceManager, ComplianceEngineer |
| GET    | `/api/sites/{id}/inspections/{inspection_id}` | Get a specific Inspection | InspectorUser, ComplianceManager, ComplianceEngineer |
| POST   | `/api/sites/{id}/inspections/{inspection_id}/submit` | Submit an Inspection | InspectorUser |
| POST   | `/api/sites/{id}/inspections/{inspection_id}/accept` | Accept a submitted Inspection | ComplianceManager |
| POST   | `/api/sites/{id}/inspections/{inspection_id}/reject` | Reject a submitted Inspection | ComplianceManager |
| POST   | `/api/sites/{id}/inspections/{inspection_id}/findings` | Add a finding to an Inspection | InspectorUser |
| GET    | `/api/sites/{id}/inspections/{inspection_id}/findings` | List findings on an Inspection | InspectorUser, ComplianceManager, ComplianceEngineer |
| GET    | `/api/sites/{id}/inspections/{inspection_id}/findings/{finding_id}` | Get a specific finding | InspectorUser, ComplianceManager, ComplianceEngineer |
| POST   | `/api/sites/{id}/inspections/{inspection_id}/findings/{finding_id}/start_work` | Start work on a finding | ComplianceEngineer |
| POST   | `/api/sites/{id}/inspections/{inspection_id}/findings/{finding_id}/resolve` | Resolve a finding | ComplianceEngineer |
| POST   | `/api/sites/{id}/inspections/{inspection_id}/findings/{finding_id}/verify` | Verify a resolved finding | ComplianceManager |
| POST   | `/api/sites/{id}/inspections/{inspection_id}/findings/{finding_id}/reopen` | Reopen a resolved finding | ComplianceManager |
| POST   | `/api/sites/{id}/inspections/{inspection_id}/findings/{finding_id}/dispute` | Dispute a finding | ComplianceEngineer |
| POST   | `/api/sites/{id}/inspections/{inspection_id}/findings/{finding_id}/withdraw` | Withdraw a disputed finding | InspectorUser |
| POST   | `/api/sites/{id}/retrofit-projects` | Scope a RetrofitProject | ComplianceEngineer |
| GET    | `/api/sites/{id}/retrofit-projects` | List RetrofitProjects at a Site | ComplianceEngineer, ComplianceManager, InspectorUser |
| GET    | `/api/sites/{id}/retrofit-projects/{project_id}` | Get a specific RetrofitProject | ComplianceEngineer, ComplianceManager, InspectorUser |
| POST   | `/api/sites/{id}/retrofit-projects/{project_id}/line-items` | Add a line item to a project | ComplianceEngineer |
| GET    | `/api/sites/{id}/retrofit-projects/{project_id}/line-items` | List line items on a project | ComplianceEngineer, ComplianceManager, InspectorUser |
| PATCH  | `/api/sites/{id}/retrofit-projects/{project_id}/line-items/{line_item_id}` | Update a line item | ComplianceEngineer |
| DELETE | `/api/sites/{id}/retrofit-projects/{project_id}/line-items/{line_item_id}` | Remove a line item | ComplianceEngineer |
| POST   | `/api/sites/{id}/retrofit-projects/{project_id}/finalize_estimate` | Finalize the estimate | ComplianceEngineer |
| POST   | `/api/sites/{id}/retrofit-projects/{project_id}/approve` | Approve a project | ComplianceManager |
| POST   | `/api/sites/{id}/retrofit-projects/{project_id}/start_execution` | Start execution on a project | ComplianceEngineer |
| POST   | `/api/sites/{id}/retrofit-projects/{project_id}/close` | Close a project | ComplianceManager |
| POST   | `/api/sites/{id}/retrofit-projects/{project_id}/cancel` | Cancel a project | ComplianceManager |
| POST   | `/api/sites/{id}/incidents` | Declare an Incident | ComplianceManager, SafetyManager |
| GET    | `/api/sites/{id}/incidents` | List Incidents at a Site | ComplianceManager, ComplianceEngineer, IncidentInvestigator, SafetyManager, InspectorUser |
| GET    | `/api/sites/{id}/incidents/{incident_id}` | Get a specific Incident | ComplianceManager, ComplianceEngineer, IncidentInvestigator, SafetyManager, InspectorUser |
| POST   | `/api/sites/{id}/incidents/{incident_id}/start_investigation` | Start investigating an Incident | IncidentInvestigator |
| POST   | `/api/sites/{id}/incidents/{incident_id}/define_capa` | Define CAPA on an Incident | IncidentInvestigator |
| POST   | `/api/sites/{id}/incidents/{incident_id}/close` | Close an Incident | ComplianceManager |
| POST   | `/api/sites/{id}/incidents/{incident_id}/reopen` | Reopen a closed Incident | ComplianceManager |
| POST   | `/api/sites/{id}/incidents/{incident_id}/capa-actions` | Author a CAPA action | IncidentInvestigator |
| GET    | `/api/sites/{id}/incidents/{incident_id}/capa-actions` | List CAPA actions on an Incident | IncidentInvestigator, ComplianceManager, ComplianceEngineer |
| POST   | `/api/sites/{id}/incidents/{incident_id}/capa-actions/{capa_id}/start` | Start a CAPA action | IncidentInvestigator |
| POST   | `/api/sites/{id}/incidents/{incident_id}/capa-actions/{capa_id}/close` | Close a CAPA action | IncidentInvestigator |
| POST   | `/_clock/set_current_utc` | Advance the logical clock | PlatformAdmin |
| GET    | `/api/dust-samples/{id}` | Get a DustSample by id (flat) | ComplianceEngineer, ComplianceManager, InspectorUser |
| GET    | `/api/collectors/{id}` | Get a Collector by id (flat) | ComplianceEngineer, ComplianceManager, InspectorUser, SafetyManager |
| GET    | `/api/housekeeping-programs/{id}` | Get a HousekeepingProgram by id (flat) | ComplianceEngineer, ComplianceManager, HousekeepingAuditor, InspectorUser |
| GET    | `/api/inspections/{id}` | Get an Inspection by id (flat) | InspectorUser, ComplianceManager, ComplianceEngineer |
| GET    | `/api/inspection-findings/{id}` | Get an InspectionFinding by id (flat) | InspectorUser, ComplianceManager, ComplianceEngineer |
| GET    | `/api/retrofit-projects/{id}` | Get a RetrofitProject by id (flat) | ComplianceEngineer, ComplianceManager, InspectorUser |
| GET    | `/api/incidents/{id}` | Get an Incident by id (flat) | ComplianceManager, ComplianceEngineer, IncidentInvestigator, SafetyManager, InspectorUser |
| GET    | `/api/dust-samples/{id}/collectors` | List Collectors referencing a DustSample | ComplianceEngineer, ComplianceManager, InspectorUser |
| GET    | `/api/housekeeping-programs/{id}/audits` | List audits under a program (flat) | ComplianceEngineer, ComplianceManager, HousekeepingAuditor, InspectorUser |
| GET    | `/api/collectors/{id}/hot-work-permits` | List HotWorkPermits referencing a Collector | SafetyManager, ComplianceManager, ComplianceEngineer, HotWorkPerformer, InspectorUser |
| GET    | `/api/collectors/{id}/incidents` | List Incidents referencing a Collector | ComplianceManager, ComplianceEngineer, IncidentInvestigator, SafetyManager, InspectorUser |
| GET    | `/api/collectors/{id}/inspection-findings` | List InspectionFindings referencing a Collector | InspectorUser, ComplianceManager, ComplianceEngineer |
| GET    | `/api/inspections/{id}/findings` | List findings under an Inspection (flat) | InspectorUser, ComplianceManager, ComplianceEngineer |
| GET    | `/api/inspection-findings/{id}/retrofit-projects` | List RetrofitProjects triggered by a finding | ComplianceEngineer, ComplianceManager, InspectorUser |
| GET    | `/api/retrofit-projects/{id}/line-items` | List line items under a project (flat) | ComplianceEngineer, ComplianceManager, InspectorUser |
| GET    | `/api/incidents/{id}/capa-actions` | List CAPA actions under an Incident (flat) | IncidentInvestigator, ComplianceManager, ComplianceEngineer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_POSTURE_STOP_WORK` | 409 Conflict |
| `ERR_VENT_UNDERSIZED` | 422 Unprocessable Entity |
| `ERR_FILTER_CHANGE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_COLLECTOR_BUSY` | 422 Unprocessable Entity |
| `ERR_COLLECTOR_HAS_OPEN_FINDING` | 422 Unprocessable Entity |
| `ERR_PERMIT_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_PERMIT_WINDOW_INACTIVE` | 422 Unprocessable Entity |
| `ERR_PERMIT_OVERLAP` | 422 Unprocessable Entity |
| `ERR_FIRE_WATCH_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_FIRE_WATCH_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_NO_COMBUSTIBLE_DUST` | 422 Unprocessable Entity |
| `ERR_SOD_VIOLATION` | 422 Unprocessable Entity |
| `ERR_AUDIT_NOT_DUE` | 422 Unprocessable Entity |
| `ERR_PROJECT_EMPTY` | 422 Unprocessable Entity |
| `ERR_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TRIGGER_FINDING_INVALID` | 422 Unprocessable Entity |
| `ERR_TRIGGER_FINDING_OPEN` | 422 Unprocessable Entity |
| `ERR_CAPA_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ROOT_CAUSE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CAPA_OPEN` | 422 Unprocessable Entity |
| `ERR_INTERNAL` | 500 Internal Server Error |
