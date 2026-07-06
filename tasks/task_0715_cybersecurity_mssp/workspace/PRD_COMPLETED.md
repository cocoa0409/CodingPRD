# Cybersecurity MSSP API — Product Requirements Document

## 1. Introduction

Managed Security Service Providers (MSSPs) operate a Security Operations Center on behalf of many client organizations at once, and the work spans a wide arc: authorizing and running sanctioned vulnerability scans and penetration tests, tracking the findings those tests produce through remediation, watching SIEM and EDR telemetry and triaging the alerts it raises, escalating genuine incidents into a structured response, and standing behind the client when an external compliance auditor comes calling for SOC 2, HIPAA, or PCI attestation. Every one of these activities consumes a finite pool of contracted labor hours, and every one of them leaves a trail that a regulator may later demand to inspect.

This document specifies the REST API that backs that operation. The platform's central tension is that aggressive, authorized offensive testing must coexist with a defensive posture that can lock the whole client down the moment a serious incident is in flight — and that the labor budget granted under a retainer must be reserved, consumed, and reconciled honestly across billing periods. The API therefore models authorization gates, segregation-of-duties controls, optimistic-concurrency protection on the two collections most prone to stale writes, and a tamper-evident audit log that records who did what to which resource. Readers implementing against this specification should treat the retainer ledger, the client posture, and the audit chain as cross-cutting invariants that many otherwise-unrelated operations must respect.

A note on time: the system runs on a **logical clock** rather than wall-clock time, so that authorization windows, SLA deadlines, and escalation deadlines can be exercised deterministically. The server's startup default clock reads `2026-03-01T00:00:00Z`, and until an operator sets it explicitly the clock stays at exactly that default and never falls back to the host's real time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming that principal's role. If either header is missing, or if `X-User-Role` is not one of the known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are five roles, spelled exactly: `PlatformAdmin`, `EngagementLead`, `SocAnalyst`, `Auditor`, and `ClientContact`. The `PlatformAdmin` is the MSSP operator who provisions clients, drives the retainer and billing-period lifecycle, and may ingest alerts. The `EngagementLead` runs assessments: engagements, scans, finding retests, incident escalation and resolution, and reports. The `SocAnalyst` lives in the alert and incident world — ingesting and triaging alerts, promoting them to incidents, and acknowledging, containing, and reopening incidents — and also records findings. The `Auditor` runs the compliance-audit lifecycle and approves, rejects, or attests evidence. The `ClientContact` is the client-side representative who signs engagement authorizations and drives finding remediation.

All five roles carry an **opaque** identity. When `X-User-Role` is any of `PlatformAdmin`, `EngagementLead`, `SocAnalyst`, `Auditor`, or `ClientContact`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity's `id`. The server may record such an identifier where a workflow calls for it — for example, the `authorization_signed_by` it stamps on an engagement, the `submitted_by` and `accepted_by` it stamps on a finding, the `triaged_by` it stamps on an alert, the `submitted_by` it stamps on a piece of evidence, or the `actor_user_id` it records on an audit-log entry — but it never compares `X-User-ID` against any entity's `id` to establish ownership. Segregation-of-duties checks compare one recorded `X-User-ID` against another recorded `X-User-ID` (for example, an approver's id against a submitter's id), never against a resource primary key.

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

### 2.3. Pagination

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100; the `offset` defaults to 0 and must be at least 0. A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400). Lists are returned sorted by `created_at` in ascending order. The pagination fields surfaced in the response `meta` are `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the count of all matching rows before the page window is applied and `has_more` is true when rows remain beyond the returned page.

### 2.4. Common Resource Properties and Versioning

Every resource is identified by an `id`, which is a server-minted UUID carrying no type prefix. Most resources also carry `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and an integer `version` that starts at 1 and increments by one on every mutation of that resource. The `created_at` is fixed at creation; `updated_at` is refreshed on every mutation.

One entity is exempt from this rule. An **audit-log entry** carries only `id` and `created_at`; it has neither `updated_at` nor `version`, because the log is append-only and entries are never mutated after they are written. The fields an audit-log entry does carry are `client_id`, `actor_role` (the `X-User-Role` that performed the action), `actor_user_id` (the `X-User-ID` that performed the action), `action` (an action verb such as `FINDING_ACCEPTED` or `INCIDENT_ESCALATED`), `target_entity` (the entity type the action targeted), `target_id` (the id of the targeted entity), `prev_hash` (the `entry_hash` of the previous audit-log entry for the same client, empty for the first entry in a client's chain), and `entry_hash` (a hash computed over the tuple of `prev_hash`, `action`, `target_id`, and `created_at`, making the chain tamper-evident). Each client maintains its own independent chain.

### 2.5. Resource Discovery and Path Validation

The topology is flat: entities are peer collections linked by foreign keys, and there is no nesting in URL paths. A scan is discovered by filtering the scan collection on `engagement_id`; a finding by filtering the finding collection on `scan_id`, `asset_id`, `client_id`, `severity`, `status`, or `linked_incident_id`; evidence by filtering on `audit_id`, `control_ref`, `status`, or `finding_id`; and so on for every child collection. When a request carries a resource id in its path, that id must resolve to an existing resource or the request is rejected with `ERR_NOT_FOUND` (HTTP 404); where multiple path ids appear they are validated left to right. When a create request carries a foreign-key field in its body, that key must reference an existing resource owned by the same client, or the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404).

### 2.6. Optimistic Concurrency Control

Two create operations are guarded by optimistic concurrency control against a parent entity's `version`. Creating a scan requires the body field `expected_engagement_version`, carrying the client's last observed `version` of the target engagement. An engagement's `version` advances whenever it transitions — for instance, signing authorization reserves retainer hours and bumps the version, and creating a sibling scan under the same engagement also bumps it. If `expected_engagement_version` does not equal the engagement's current `version`, the scan create is rejected with `ERR_STALE_VERSION` (HTTP 412), because the engagement state the scan was meant to run against may no longer hold and the caller must re-read before proceeding.

Symmetrically, submitting audit evidence requires the body field `expected_audit_version`, carrying the submitter's last observed `version` of the target compliance audit. An audit's `version` advances when it changes phase (for example, when it enters fieldwork) and when a sibling evidence approval recomputes its readiness. If `expected_audit_version` does not equal the audit's current `version`, the evidence submission is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the submitter to re-read the audit's phase before contributing. No other endpoint takes a version field; OCC applies only to scan creation and evidence submission.

### 2.7. Retainer Hours and the Ledger Principle

Every client is granted a fixed number of managed-defense labor hours per billing period, recorded as `retainer_hours_per_period`. For each billing period a `RetainerLedger` row tracks that budget. At the moment a period opens, the ledger snapshots the client's `retainer_hours_per_period` into `hours_granted`; it then tracks `hours_reserved` (hours committed by authorized engagements not yet completed), `hours_consumed` (hours actually spent by completed scans and resolved incidents), and `hours_available`, which is `hours_granted` minus `hours_reserved` minus `hours_consumed`. Available hours may go negative only under an overage policy. A ledger row carries `client_id`, `period_index`, and a `status` of either `OPEN` or `CLOSED`; only the `OPEN` row for the client's current period accepts new reservations and consumption.

The available-hours figure is recomputed whenever an engagement is authorized, cancelled, or expired, whenever a scan completes, and whenever an incident resolves. The reserved figure is the sum, over engagements of this client in this `period_index` whose `status` is `AUTHORIZED`, of each engagement's `estimated_hours`, less the sum over completed scans under those engagements of the smaller of each scan's `actual_hours` and that engagement's remaining reservation, with each engagement's contribution floored at zero before summing. The consumed figure is the sum of `actual_hours` over the client's `COMPLETED` scans whose work fell in this period plus the sum of `response_hours` over the client's `RESOLVED` incidents resolved in this period. Two consistent readings of the same budget exist over time: at authorize time the **full estimate is reserved up front** as a worst-case projection, and after scans and incidents complete that optimistic reservation is released and replaced by the **measured actual consumption**, so the difference between estimate and actual flows back into available hours. All hours are kept to two decimal places, rounded half up, and the per-engagement reservation floor at zero is applied before summing.

### 2.8. Defense Posture

Each client carries a computed `posture` that gates offensive operations. The posture is `OPEN` normally, rises to `HEIGHTENED` when any open incident has a severity of `HIGH` or higher, and rises to `LOCKDOWN` when any incident is in the `ESCALATED` state. Posture is recomputed whenever an incident is promoted, escalated, resolved, or reopened. While a client is in `LOCKDOWN`, new engagement authorizations are frozen, engagement starts are frozen, and report publication is frozen; each such attempt is rejected with `ERR_POSTURE_LOCKDOWN` (HTTP 409). A client also carries a computed `open_critical_findings` count — the number of findings whose `severity` is `CRITICAL` and whose `status` is none of `REMEDIATED`, `RISK_ACCEPTED`, or `FALSE_POSITIVE` — and a `status` of `ACTIVE`, `SUSPENDED`, or `OFFBOARDED`.

### 2.9. Severity, Scoring, and SLA Precision

Several quantities are derived and must follow exact precision rules. Finding `severity` is an enum derived from the CVSS base score and an asset-criticality escalation. Alert `triage_priority` is a banded value derived from a weighted score that is summed to full precision and then rounded **half up to two decimal places exactly once** at the end (sum-then-round, never round-each-term). Compliance `readiness_pct` is a percentage rounded half up to two decimal places. Retainer hour figures are likewise carried to two decimal places, half up. SLA and escalation deadlines are computed by exact hours arithmetic against the relevant anchor timestamp, and the breach comparisons against the logical clock are strict (the deadline must be strictly passed). The detailed formulas live in §3 where the workflows that produce these values are described.

### 2.10. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order so that the surfaced error is deterministic. Authentication is checked first, then authorization, then existence of path-referenced resources, then existence of body foreign keys, then request-body shape and enum validity, then optimistic-concurrency version match, then whether the target is in a state the transition is allowed from, and only then the business-safety, referential, temporal, and fiscal checks specific to the operation. Concretely: a missing header surfaces as `ERR_UNAUTHENTICATED` before anything else; a forbidden role surfaces as `ERR_UNAUTHORIZED` before a 404; a missing path resource surfaces as `ERR_NOT_FOUND` before a body FK is examined; a bad body FK surfaces as `ERR_FK_NOT_FOUND`; a malformed body surfaces as `ERR_INVALID_REQUEST`; a stale version surfaces as `ERR_STALE_VERSION`; and a wrong current state surfaces as `ERR_INVALID_STATE` (HTTP 409) before any operation-specific business rule (posture lockdown, segregation of duties, window, retainer, and the rest) is evaluated. Pagination validity (`ERR_INVALID_PAGINATION`) guards list endpoints.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Client and Opening the Retainer

A `PlatformAdmin` creates a client by supplying its `name`, its service `tier` — one of `ESSENTIAL`, `ADVANCED`, or `ELITE` — and its `retainer_hours_per_period`, which must be at least zero. The new client starts with `status` `ACTIVE`, a `current_period_index` of 0, a `posture` of `OPEN`, and an `open_critical_findings` count of 0. Creating the client also opens the first retainer ledger: an `OPEN` `RetainerLedger` for period 0 whose `hours_granted` equals the client's `retainer_hours_per_period`.

The billing period advances when a `PlatformAdmin` triggers the advance-period capability on the client. That operation increments `current_period_index` by one, transitions the currently open ledger to `CLOSED`, and opens a fresh ledger for the new period. It also performs an expiry sweep: any engagement still in `AUTHORIZED` whose `authorized_window_end` is now behind the logical clock and which never started is moved to `EXPIRED`, releasing its reserved hours. A `PlatformAdmin` may also suspend a client, moving the client `status` to `SUSPENDED`. Retainer ledgers are read back through the ledger collection, filtered by `client_id` and `period_index`, exposing the computed `hours_reserved`, `hours_consumed`, and `hours_available`.

### 3.2. Registering Assets

An asset is registered by a `PlatformAdmin` or `EngagementLead` against a client, carrying the asset's `client_id`, `hostname`, `ip_address`, business `criticality` — one of `LOW`, `MEDIUM`, `HIGH`, or `CROWN_JEWEL` — and optionally its `exposure`, which is `INTERNAL` by default but may be `EXTERNAL`. An asset opens with `status` `ACTIVE` and may later move to `QUARANTINED` (during incident containment) or `DECOMMISSIONED`. The `hostname` must be unique per client among assets that are not `DECOMMISSIONED`; a collision is rejected with `ERR_DUPLICATE_HOSTNAME` (HTTP 409), so a hostname freed by decommissioning may be reused. Decommissioning an asset, available to a `PlatformAdmin` or `EngagementLead`, moves its `status` to `DECOMMISSIONED`.

### 3.3. Authorizing and Running an Engagement

An `EngagementLead` drafts an engagement against a client, supplying the `client_id`, the `kind` — either `VULN_SCAN` or `PENTEST` — the `authorized_window_start` and `authorized_window_end` that bound when sanctioned testing may run, the `estimated_hours` of labor (which must be greater than zero), and the `scope_asset_ids` array naming the assets explicitly in scope; a penetration test may only touch assets in that list. A new engagement opens in `DRAFT`.

Authorization is the gate that commits budget, and only a `ClientContact` may sign it, advancing the engagement `DRAFT → AUTHORIZED`. Several preconditions guard this transition, and they surface distinct errors, evaluated in this order. The client must not be in `LOCKDOWN`, or the request is rejected with `ERR_POSTURE_LOCKDOWN`. The client must then be `ACTIVE`, or the request is rejected with `ERR_CLIENT_NOT_ACTIVE`. Every id in `scope_asset_ids` must be an `ACTIVE` asset belonging to this engagement's client, or the request is rejected with `ERR_SCOPE_ASSET_INVALID`. If the engagement's `kind` is `PENTEST`, no other engagement of kind `PENTEST` in status `AUTHORIZED` or `ACTIVE` may share any asset in `scope_asset_ids` while its authorized window overlaps this one; windows are treated as half-open intervals running from `authorized_window_start` up to but not including `authorized_window_end`, so two windows where one's end exactly equals the other's start do not conflict, and a genuine overlap is rejected with `ERR_WINDOW_OVERLAP`. Finally, the open retainer ledger for the client's current period must be `OPEN` (else `ERR_PERIOD_CLOSED`) and its `hours_available` must be at least the engagement's `estimated_hours`, or the request is rejected with `ERR_RETAINER_EXHAUSTED`. On success the engagement stamps `authorization_signed_by` with the signing `ClientContact`'s `X-User-ID`, captures the client's `current_period_index` into the engagement's `period_index`, reserves `estimated_hours` on the open ledger (raising `hours_reserved` and lowering `hours_available`), and bumps the engagement's own version.

Beginning sanctioned testing is an `EngagementLead` action that advances `AUTHORIZED → ACTIVE`. It is permitted only when the logical clock is at or after `authorized_window_start` and at or before `authorized_window_end` — otherwise `ERR_OUTSIDE_WINDOW` — and only when the client is not in `LOCKDOWN`, else `ERR_POSTURE_LOCKDOWN`. Completing an engagement is an `EngagementLead` action advancing `ACTIVE → COMPLETED`; it is blocked while any scan under the engagement is still `QUEUED` or `RUNNING`, which surfaces as `ERR_SCANS_IN_FLIGHT`. On completion the engagement releases any reservation not yet turned into consumption — reducing `hours_reserved` by the estimate minus the actual hours already moved to consumption, floored at zero — and recomputes available hours.

An `EngagementLead` may also cancel an engagement. Cancelling a `DRAFT` engagement (`DRAFT → CANCELLED`) has no ledger effect because nothing was ever reserved. Cancelling an `AUTHORIZED` engagement (`AUTHORIZED → CANCELLED`) is a compensating action: it releases the full reservation by reducing `hours_reserved` by `estimated_hours` and recomputes available hours, keeping reservation accounting conserved. The system-driven expiry described in §3.1 (`AUTHORIZED → EXPIRED`) likewise releases the full `estimated_hours` reservation as a compensating action. Authorizing, starting, completing, and cancelling all bump the engagement's version and append an audit-log entry (`ENGAGEMENT_AUTHORIZED`, `ENGAGEMENT_STARTED`, `ENGAGEMENT_COMPLETED`, `ENGAGEMENT_CANCELLED`, and `ENGAGEMENT_EXPIRED` for the expiry sweep).

### 3.4. Scanning Within the Window

A scan is queued under an engagement by an `EngagementLead`, who supplies the `engagement_id` and the `expected_engagement_version` carrying the engagement version last observed (see §2.6). On success the scan opens in `QUEUED`, copies the engagement's `client_id` onto itself, and bumps the parent engagement's version. The scan also tracks the system-stamped `started_at` and `completed_at`, the input `actual_hours` and `raw_finding_count` supplied at completion (with `actual_hours` null and `raw_finding_count` defaulting to 0 until then), and a `status` of `QUEUED`, `RUNNING`, `COMPLETED`, or `ABORTED`.

Starting a queued scan advances `QUEUED → RUNNING` and is an `EngagementLead` action. The parent engagement must be `ACTIVE`, or the request is rejected with `ERR_ENGAGEMENT_NOT_ACTIVE`. The logical clock must fall within the parent engagement's authorized window, else `ERR_OUTSIDE_WINDOW`. And no other scan in `RUNNING` status under the same engagement may have a closed buffered interval running from its `started_at` through 24 hours after its `started_at` that contains the clock — a new scan may not start within 24 hours of another running scan on the same engagement — or the request is rejected with `ERR_SCAN_WINDOW_OVERLAP`. The interval is closed and buffered, so a clock landing exactly 24 hours after another scan's start still collides. On success the scan stamps `started_at` with the clock.

Completing a running scan advances `RUNNING → COMPLETED` and requires the `actual_hours` value, which must be supplied and at least zero, or the request fails with `ERR_INVALID_REQUEST`; the optional `raw_finding_count` is persisted alongside it. Completion stamps `completed_at` with the clock, and it debits the retainer by recomputing the open ledger from the canonical §2.7 formulas rather than by applying incremental deltas: `hours_consumed` rises by `actual_hours`, and `hours_reserved` is set to the §2.7 reserved sum. Because that sum ranges only over engagements whose `status` is still `AUTHORIZED`, and a scan can only complete while its parent engagement is `ACTIVE` (the engagement left `AUTHORIZED` when it started), the parent engagement no longer contributes to reserved at all at completion time — so `hours_reserved` does not fall by `actual_hours` here; the engagement's reservation already dropped out of the reserved figure at start. Available hours are then recomputed as `hours_granted` minus `hours_reserved` minus `hours_consumed`. A scan may be aborted from either `QUEUED` or `RUNNING` (`QUEUED → ABORTED` or `RUNNING → ABORTED`); abortion never debits the ledger because the scan never reported actual hours. The relevant audit actions are `SCAN_STARTED`, `SCAN_COMPLETED`, and `SCAN_ABORTED`.

### 3.5. Findings: Severity, SLA, and the Remediation Loop

A finding is recorded against a completed scan by a `SocAnalyst` or `EngagementLead`, who supplies the `scan_id`, the `asset_id`, a `title`, and the `cvss_base` score (between 0.0 and 10.0 inclusive). The finding copies the `client_id` from its scan, stamps `submitted_by` with the recording principal's `X-User-ID` (the segregation-of-duties anchor), and computes both its `severity` and its `sla_due_at`. A finding opens in `OPEN` and carries a system `accepted_by`, a system `linked_incident_id` (set only when a critical finding escalates into an incident, null otherwise), and a computed `sla_breached` flag.

**Severity** is derived in two steps. First a base band is chosen from `cvss_base`: a score of exactly 0.0 is `INFO`; a score from 0.1 up to but not including 4.0 is `LOW`; from 4.0 up to but not including 7.0 is `MEDIUM`; from 7.0 up to but not including 9.0 is `HIGH`; and 9.0 or above (through 10.0) is `CRITICAL`. The comparison at each floor is inclusive, so reaching the floor crosses up into the higher band. Second, the asset's `criticality` may escalate the band by exactly one step, capped at `CRITICAL`: a `CROWN_JEWEL` asset always bumps the severity up one band, and a `HIGH`-criticality asset bumps it up one band only when the base band is `MEDIUM` or `HIGH`. Assets of `LOW` or `MEDIUM` criticality never escalate severity. The ordered bands, lowest to highest, are `INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.

**The remediation SLA deadline** is projected forward at creation and frozen against the finding's `created_at`. A base window in hours is chosen by the computed severity: `CRITICAL` findings get 24 hours, `HIGH` findings 72 hours, `MEDIUM` findings 168 hours (one week), and `LOW` findings 720 hours (thirty days); `INFO` findings have no SLA and their `sla_due_at` is null. That base window is then scaled by a tier multiplier that shrinks the window for higher tiers — `ESSENTIAL` clients use the full window (multiplier 1.0), `ADVANCED` clients use three-quarters of it (multiplier 0.75), and `ELITE` clients use half of it (multiplier 0.5). The `sla_due_at` is the finding's `created_at` plus the base window multiplied by the tier multiplier, expressed in hours; for `INFO` findings it stays null. The deadline does not move if severity later changes — it is anchored to `created_at`. The `sla_breached` flag, by contrast, is evaluated live against the logical clock on every read: it is true exactly when the clock is strictly past `sla_due_at` and the finding's `status` is none of `REMEDIATED`, `RISK_ACCEPTED`, or `FALSE_POSITIVE`.

Recording a finding recomputes the client's `open_critical_findings`. From `OPEN`, a finding can travel several paths. A `ClientContact` begins remediation (`OPEN → REMEDIATION_IN_PROGRESS`), permitted only when the parent scan is `COMPLETED`, else `ERR_SCAN_NOT_COMPLETED`. The contact then submits the work for retest (`REMEDIATION_IN_PROGRESS → REMEDIATION_SUBMITTED`). An `EngagementLead` retests, supplying `retest_passed`; the same retest endpoint forks on that boolean and on segregation of duties. The acting lead's `X-User-ID` must differ from the finding's `submitted_by`, or the retest is rejected with `ERR_SEGREGATION_OF_DUTIES`. When `retest_passed` is false, the finding goes `REMEDIATION_SUBMITTED → RETEST_FAILED`; when `retest_passed` is true, it goes `REMEDIATION_SUBMITTED → REMEDIATED`, stamping `accepted_by` with the lead's `X-User-ID` and recomputing the client's `open_critical_findings`. A failed retest re-enters the loop: the same start-remediation action drives `RETEST_FAILED → REMEDIATION_IN_PROGRESS`, and the cycle repeats until a retest passes.

Two other terminal paths exist out of `OPEN`. A `ClientContact` may risk-accept a finding (`OPEN → RISK_ACCEPTED`), but only when the finding's `severity` is not `CRITICAL`; an attempt to risk-accept a `CRITICAL` finding is rejected with `ERR_CANNOT_ACCEPT_CRITICAL`. An `EngagementLead` may mark a finding a false positive (`OPEN → FALSE_POSITIVE`), provided the acting lead's `X-User-ID` differs from the finding's `submitted_by`, else `ERR_SEGREGATION_OF_DUTIES`. Both of these recompute the client's `open_critical_findings`. The audit actions across this lifecycle are `REMEDIATION_STARTED`, `REMEDIATION_SUBMITTED`, `RETEST_FAILED`, `REMEDIATION_RESTARTED` (for the loop back from a failed retest), `FINDING_REMEDIATED`, `RISK_ACCEPTED`, and `FALSE_POSITIVE`.

### 3.6. Alert Ingestion, Triage, and Promotion

A `SocAnalyst` or `PlatformAdmin` ingests an alert from a detector, supplying the `client_id`, the `asset_id` the alert fired on, the `source` (either `SIEM` or `EDR`), and the detector's `raw_score` (between 0 and 100). Ingestion computes the alert's `triage_priority`. An alert opens in `NEW` and carries a system `triaged_by`, a system `promoted_incident_id`, and a `status` of `NEW`, `TRIAGED`, `DISMISSED`, or `PROMOTED`.

**Triage priority** is a weighted score banded into four levels. The weighted sum is the `raw_score` multiplied by 0.6, plus a criticality weight drawn from the alert's asset — 0 for `LOW` criticality, 10 for `MEDIUM`, 20 for `HIGH`, and 35 for `CROWN_JEWEL` — plus an exposure bonus of 15 when the asset's `exposure` is `EXTERNAL` and 0 otherwise. That whole sum is computed at full precision and then rounded half up to two decimal places exactly once. The banding is inclusive at each floor: a score of 80 or above is `P1`, a score from 55 up to 79.99 is `P2`, a score from 30 up to 54.99 is `P3`, and anything below 30 is `P4`.

Triaging an alert is a `SocAnalyst` action advancing `NEW → TRIAGED`. Its asset must resolve to an asset whose `status` is not `DECOMMISSIONED`, or the request is rejected with `ERR_ASSET_DECOMMISSIONED`; on success the alert recomputes its `triage_priority` from the asset's current `criticality` and `exposure` and stamps `triaged_by`. From `TRIAGED`, an alert can be dismissed or promoted. A `SocAnalyst` dismisses an alert (`TRIAGED → DISMISSED`), but only when its `triage_priority` is `P3` or `P4`; `P1` and `P2` alerts must be promoted rather than dismissed, and an attempt to dismiss one is rejected with `ERR_CANNOT_DISMISS_HIGH_PRIORITY`. Promotion is a `SocAnalyst` action advancing `TRIAGED → PROMOTED`, permitted only when the client's `status` is `ACTIVE`, else `ERR_CLIENT_NOT_ACTIVE`. Promotion is a cascade: it creates a new incident in `DETECTED` whose `triggering_alert_id` is this alert's id and whose severity maps from the alert's `triage_priority` (`P1` → `CRITICAL`, `P2` → `HIGH`, `P3` → `MEDIUM`, `P4` → `LOW`), sets the alert's `promoted_incident_id` to the new incident's id, and recomputes the client's `posture` (a new incident may raise posture to `HEIGHTENED` or `LOCKDOWN`). The audit actions are `ALERT_TRIAGED`, `ALERT_DISMISSED`, and `ALERT_PROMOTED`.

### 3.7. Incident Response and the Containment Cycle

An incident carries a `client_id`, a `triggering_alert_id` (the alert that was promoted into it, or null for incidents that originate from findings), an input `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, and an input `response_hours` (the IR labor consumed, supplied at resolution and at least zero, defaulting to 0). It also carries a computed `escalation_deadline_at` and `escalation_breached` flag, a computed `contained_count`, a system `resolved_period_index` (null until first resolution), and a system `quarantined_asset_id` (null when none). An incident opens in `DETECTED`. The `escalation_deadline_at` is the incident's `created_at` plus the tier-and-severity response-SLA hours — a base window chosen by severity (`CRITICAL` 24 hours, `HIGH` 72 hours, `MEDIUM` 168 hours, `LOW` 720 hours) and then scaled by the same tier multiplier the finding SLA uses (`ESSENTIAL` 1.0, `ADVANCED` 0.75, `ELITE` 0.5) — and `escalation_breached` becomes true (evaluated live against the logical clock on every read) once the clock is strictly past `escalation_deadline_at` while the incident is still in `DETECTED`.

A `SocAnalyst` acknowledges an incident (`DETECTED → ACKNOWLEDGED`). From `ACKNOWLEDGED`, a `SocAnalyst` contains it (`ACKNOWLEDGED → CONTAINED`), incrementing `contained_count` by one each time. The contain action accepts an optional `quarantine_asset` flag (defaulting to false when omitted); when true, the triggering alert's asset must resolve and be `ACTIVE` — otherwise the request is rejected with `ERR_INVALID_STATE` — and containment sets that asset's `status` to `QUARANTINED` and records its id in the incident's `quarantined_asset_id` — a cross-entity cascade.

Escalation is an `EngagementLead` action available from either `DETECTED` or `ACKNOWLEDGED` (`DETECTED → ESCALATED` or `ACKNOWLEDGED → ESCALATED`), permitted only when the incident's `severity` is `HIGH` or `CRITICAL`; escalating a `LOW` or `MEDIUM` incident is rejected with `ERR_CANNOT_ESCALATE_LOW`. Escalation recomputes the client's `posture` into `LOCKDOWN`, freezing new engagement authorizations and starts and report publication until the escalation clears.

Resolving an incident is an `EngagementLead` action available from either `CONTAINED` or `ESCALATED` (`CONTAINED → RESOLVED` or `ESCALATED → RESOLVED`). Resolution requires `response_hours` supplied and at least zero (else `ERR_INVALID_REQUEST`) and requires the retainer ledger for the client's current period to be `OPEN` (else `ERR_PERIOD_CLOSED`). On resolution the incident captures the client's `current_period_index` into `resolved_period_index`, debits the retainer by raising `hours_consumed` by `response_hours` and recomputing available hours, and recomputes the client's `posture` (resolving may drop posture back to `OPEN` or `HEIGHTENED`, and `LOCKDOWN` lifts once no `ESCALATED` incident remains). If the incident had quarantined an asset, resolution reverses that quarantine — setting that asset's `status` back to `ACTIVE` and clearing `quarantined_asset_id` — as a compensating action that keeps quarantine accounting conserved.

A resolved incident can be reopened by a `SocAnalyst` (`RESOLVED → REOPENED`), but only within the same billing period it was resolved in: the client's `current_period_index` must equal the incident's `resolved_period_index`, or the reopen is rejected with `ERR_REOPEN_WINDOW_CLOSED`. Reopening recomputes the client's `posture`, which may re-raise it. A reopened incident can be contained again (`REOPENED → CONTAINED`), once more incrementing `contained_count`. The audit actions across incident handling are `INCIDENT_ACKNOWLEDGED`, `INCIDENT_CONTAINED`, `INCIDENT_ESCALATED`, `INCIDENT_RESOLVED`, and `INCIDENT_REOPENED`.

### 3.8. Compliance Audits and Evidence

A `ComplianceAudit` is created by an `Auditor` or `EngagementLead` against a client, carrying the `client_id`, the `framework` (one of `SOC2`, `HIPAA`, or `PCI`), and the `required_control_count` — the number of controls that must each be covered by at least one approved evidence item, which must be greater than zero. The audit opens in `PLANNING` with a computed `readiness_pct` of 0. Its `status` runs through `PLANNING`, `FIELDWORK`, `READY`, `ATTESTED`, or `FAILED`.

Evidence is submitted against an audit by an `Auditor` or `EngagementLead`, carrying the `audit_id`, the `control_ref` it covers (a control identifier such as a SOC 2 control reference), an optional `finding_id` linking a remediated finding used as evidence, and the `expected_audit_version` for the optimistic-concurrency check of §2.6. Submitted evidence stamps `submitted_by` with the submitter's `X-User-ID`, opens in `SUBMITTED`, and bumps the parent audit's version. An `Auditor` approves evidence (`SUBMITTED → APPROVED`) only when the parent audit is in `FIELDWORK` (else `ERR_AUDIT_NOT_IN_FIELDWORK`) and only when the approver's `X-User-ID` differs from the evidence's `submitted_by` (else `ERR_SEGREGATION_OF_DUTIES`); approval recomputes the parent audit's `readiness_pct` and bumps the audit's version. An `Auditor` may instead reject evidence (`SUBMITTED → REJECTED`), again only when the rejecter's `X-User-ID` differs from the `submitted_by`, else `ERR_SEGREGATION_OF_DUTIES`; rejection also recomputes `readiness_pct`.

**Readiness** is the percentage of required controls that are covered. It counts the number of distinct `control_ref` values among approved evidence rows for the audit — two approved evidences for the same control count once — caps that count at `required_control_count` so extra controls cannot push past 100, and computes one hundred times the covered count divided by `required_control_count`, rounded half up to two decimal places.

The audit lifecycle is driven entirely by an `Auditor`. Beginning fieldwork advances `PLANNING → FIELDWORK` and bumps the audit's version. Marking the audit ready advances `FIELDWORK → READY` but is doubly gated: `readiness_pct` must equal 100.00, or the request is rejected with `ERR_AUDIT_NOT_READY`, and the client's `open_critical_findings` must be zero, or it is rejected with `ERR_OPEN_CRITICAL_FINDINGS` — an audit cannot go ready while its client still has open critical findings. Attesting advances `READY → ATTESTED` and enforces segregation of duties at the audit level: the attesting `Auditor`'s `X-User-ID` must not have submitted any evidence for this audit, or the attestation is rejected with `ERR_SEGREGATION_OF_DUTIES`. An `Auditor` may fail an audit during fieldwork (`FIELDWORK → FAILED`), and may drop a ready audit back to fieldwork (`READY → FIELDWORK`) when new evidence is required, completing the audit's cycle. The audit actions are `AUDIT_FIELDWORK`, `AUDIT_READY`, `AUDIT_ATTESTED`, `AUDIT_FAILED`, `AUDIT_REOPENED`, `EVIDENCE_APPROVED`, and `EVIDENCE_REJECTED`.

### 3.9. Reporting and the Logical Clock

An `EngagementLead` or `Auditor` generates a report against a client, supplying the `client_id`, the `kind` (one of `ASSESSMENT`, `INCIDENT`, `COMPLIANCE`, or `RETAINER`), and an optional `subject_id` naming the engagement, incident, or compliance audit the report summarizes. Generation freezes a denormalized `snapshot` object of the current metrics — the client's `posture`, `open_critical_findings`, and `current_period_index`, a `finding_count` and `incident_count` for the client, and the open ledger's `hours_reserved`, `hours_consumed`, and `hours_available` (each zero when no open ledger exists) — into the report. A report opens in `GENERATED`. An `EngagementLead` publishes a report (`GENERATED → PUBLISHED`), but publication is blocked while the client is in `LOCKDOWN`, surfacing as `ERR_POSTURE_LOCKDOWN`. A published report may be retracted (`PUBLISHED → RETRACTED`) by an `EngagementLead`. The audit actions are `REPORT_PUBLISHED` and `REPORT_RETRACTED`.

The tamper-evident audit log is read back through its collection, filtered by `client_id`, `action`, or `target_id`, with each entry's hash-chain fields exposed for inspection. Finally, an admin-only test-driving capability sets the server's logical clock to a supplied `to_iso8601` instant; advancing the clock re-evaluates the live `sla_breached` and `escalation_breached` flags on subsequent reads. Before any such call the clock holds its startup default of `2026-03-01T00:00:00Z` and never falls back to wall-clock time.

## 4. Endpoint Definitions

New resource creation returns HTTP 201; state-changing actions and other modifications return HTTP 200; reads return HTTP 200. The request body, response body, and side effects of each endpoint are described in §3 and are not repeated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /clients | Create a client | PlatformAdmin |
| GET | /clients | List clients (paginated) | PlatformAdmin, EngagementLead, SocAnalyst, Auditor |
| GET | /clients/{id} | Get a client (includes computed posture, open_critical_findings) | PlatformAdmin, EngagementLead, SocAnalyst, Auditor, ClientContact |
| POST | /clients/{id}/advance-period | Close current ledger, increment period, open new ledger; expire stale engagements | PlatformAdmin |
| POST | /clients/{id}/suspend | Suspend a client | PlatformAdmin |
| GET | /retainer-ledgers | List retainer ledgers; filter by client_id/period_index | PlatformAdmin, EngagementLead |
| GET | /retainer-ledgers/{id} | Get a retainer ledger (computed hours) | PlatformAdmin, EngagementLead |
| POST | /assets | Register an asset | PlatformAdmin, EngagementLead |
| GET | /assets | List assets; filter by client_id/status | PlatformAdmin, EngagementLead, SocAnalyst, ClientContact |
| GET | /assets/{id} | Get an asset | PlatformAdmin, EngagementLead, SocAnalyst, ClientContact |
| POST | /assets/{id}/decommission | Decommission an asset | PlatformAdmin, EngagementLead |
| POST | /engagements | Create an engagement in DRAFT | EngagementLead |
| GET | /engagements | List engagements; filter by client_id/status | PlatformAdmin, EngagementLead, ClientContact |
| GET | /engagements/{id} | Get an engagement | PlatformAdmin, EngagementLead, ClientContact |
| POST | /engagements/{id}/authorize | Client signs authorization; reserves retainer hours | ClientContact |
| POST | /engagements/{id}/start | Begin sanctioned testing | EngagementLead |
| POST | /engagements/{id}/complete | Complete engagement; release unspent reservation | EngagementLead |
| POST | /engagements/{id}/cancel | Cancel a DRAFT or AUTHORIZED engagement; releases reservation | EngagementLead |
| POST | /scans | Queue a scan under an engagement (OCC on engagement) | EngagementLead |
| GET | /scans | List scans; filter by engagement_id/client_id/status | PlatformAdmin, EngagementLead |
| GET | /scans/{id} | Get a scan | PlatformAdmin, EngagementLead |
| POST | /scans/{id}/start | Start a queued scan (must be in engagement window) | EngagementLead |
| POST | /scans/{id}/complete | Complete scan; debits retainer by actual_hours | EngagementLead |
| POST | /scans/{id}/abort | Abort a scan | EngagementLead |
| POST | /findings | Record a finding for a completed scan; computes severity and SLA | SocAnalyst, EngagementLead |
| GET | /findings | List findings; filter by scan_id/client_id/asset_id/severity/status/linked_incident_id | PlatformAdmin, EngagementLead, SocAnalyst, ClientContact, Auditor |
| GET | /findings/{id} | Get a finding (live sla_breached) | PlatformAdmin, EngagementLead, SocAnalyst, ClientContact, Auditor |
| POST | /findings/{id}/start-remediation | Client begins (or restarts) remediation | ClientContact |
| POST | /findings/{id}/submit-remediation | Client submits remediation for retest | ClientContact |
| POST | /findings/{id}/retest | Lead retests; pass or fail (segregation of duties) | EngagementLead |
| POST | /findings/{id}/accept-risk | Client risk-accepts a non-CRITICAL finding | ClientContact |
| POST | /findings/{id}/mark-false-positive | Lead marks finding false positive (segregation of duties) | EngagementLead |
| POST | /alerts | Ingest a SIEM/EDR alert; computes triage_priority | SocAnalyst, PlatformAdmin |
| GET | /alerts | List alerts; filter by client_id/asset_id/status/triage_priority/promoted_incident_id | PlatformAdmin, EngagementLead, SocAnalyst |
| GET | /alerts/{id} | Get an alert | PlatformAdmin, EngagementLead, SocAnalyst |
| POST | /alerts/{id}/triage | Triage an alert | SocAnalyst |
| POST | /alerts/{id}/dismiss | Dismiss a low-priority alert | SocAnalyst |
| POST | /alerts/{id}/promote | Promote alert to incident | SocAnalyst |
| GET | /incidents | List incidents; filter by client_id/status/severity/triggering_alert_id/quarantined_asset_id | PlatformAdmin, EngagementLead, SocAnalyst |
| GET | /incidents/{id} | Get an incident | PlatformAdmin, EngagementLead, SocAnalyst |
| POST | /incidents/{id}/acknowledge | Acknowledge an incident | SocAnalyst |
| POST | /incidents/{id}/contain | Contain an incident; optionally quarantine the asset | SocAnalyst |
| POST | /incidents/{id}/escalate | Escalate a HIGH/CRITICAL incident | EngagementLead |
| POST | /incidents/{id}/resolve | Resolve an incident; debits retainer, reverses quarantine | EngagementLead |
| POST | /incidents/{id}/reopen | Reopen a resolved incident within the same period | SocAnalyst |
| POST | /audits | Create a compliance audit in PLANNING | Auditor, EngagementLead |
| GET | /audits | List audits; filter by client_id/framework/status | PlatformAdmin, EngagementLead, Auditor, ClientContact |
| GET | /audits/{id} | Get an audit (computed readiness_pct) | PlatformAdmin, EngagementLead, Auditor, ClientContact |
| POST | /audits/{id}/begin-fieldwork | Move audit to FIELDWORK | Auditor |
| POST | /audits/{id}/mark-ready | Mark audit READY | Auditor |
| POST | /audits/{id}/attest | Attest the audit (segregation of duties) | Auditor |
| POST | /audits/{id}/fail | Fail an audit during fieldwork | Auditor |
| POST | /audits/{id}/reopen-fieldwork | Return a READY audit to FIELDWORK | Auditor |
| POST | /evidence | Submit audit evidence for a control (OCC on audit) | Auditor, EngagementLead |
| GET | /evidence | List evidence; filter by audit_id/control_ref/status/finding_id | PlatformAdmin, EngagementLead, Auditor |
| GET | /evidence/{id} | Get an evidence item | PlatformAdmin, EngagementLead, Auditor |
| POST | /evidence/{id}/approve | Approve evidence (segregation of duties); recomputes readiness | Auditor |
| POST | /evidence/{id}/reject | Reject evidence (segregation of duties) | Auditor |
| POST | /reports | Generate a report; freezes a denormalized snapshot | EngagementLead, Auditor |
| GET | /reports | List reports; filter by client_id/kind/status | PlatformAdmin, EngagementLead, Auditor, ClientContact |
| GET | /reports/{id} | Get a report | PlatformAdmin, EngagementLead, Auditor, ClientContact |
| POST | /reports/{id}/publish | Publish a report (blocked in LOCKDOWN) | EngagementLead |
| POST | /reports/{id}/retract | Retract a published report | EngagementLead |
| GET | /audit-log | List audit-log entries; filter by client_id/action/target_id | PlatformAdmin, Auditor |
| GET | /audit-log/{id} | Get a single audit-log entry (tamper-evident hash chain fields) | PlatformAdmin, Auditor |
| POST | /_clock/set_current_utc | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_PAGINATION | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_POSTURE_LOCKDOWN | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_CANNOT_ACCEPT_CRITICAL | 409 |
| ERR_CANNOT_DISMISS_HIGH_PRIORITY | 409 |
| ERR_CANNOT_ESCALATE_LOW | 409 |
| ERR_ENGAGEMENT_NOT_ACTIVE | 409 |
| ERR_SCOPE_ASSET_INVALID | 409 |
| ERR_OUTSIDE_WINDOW | 409 |
| ERR_AUDIT_NOT_READY | 409 |
| ERR_OPEN_CRITICAL_FINDINGS | 409 |
| ERR_RETAINER_EXHAUSTED | 409 |
| ERR_PERIOD_CLOSED | 409 |
| ERR_DUPLICATE_HOSTNAME | 409 |
| ERR_REOPEN_WINDOW_CLOSED | 409 |
| ERR_ASSET_DECOMMISSIONED | 409 |
| ERR_SCANS_IN_FLIGHT | 409 |
| ERR_SCAN_NOT_COMPLETED | 409 |
| ERR_AUDIT_NOT_IN_FIELDWORK | 409 |
| ERR_CLIENT_NOT_ACTIVE | 409 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_SCAN_WINDOW_OVERLAP | 409 |
