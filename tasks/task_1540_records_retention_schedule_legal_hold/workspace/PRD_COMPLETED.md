# Records Retention Schedule & Legal Hold API — Product Requirements Document

## 1. Introduction

Corporate information governance teams live under two opposing pressures. On one side, records that outlive their regulatory retention window are a liability: they inflate discovery exposure, drive up storage spend, and become litigation risk the moment they outlast their lawful keep. On the other side, deleting too eagerly — destroying a record that is the subject of an active legal hold, or shredding content while a regulator dispute about its class's retention period is unresolved — is sanctionable spoliation. Between these two cliffs sits a tightly coordinated workflow: a retention schedule per record class and jurisdiction, defensible disposition decisions made under segregation of duties, legal holds with custodian acknowledgment tracking, and audit trails that demonstrate control to an outside examiner.

This document specifies an API for operating that workflow end to end. The system manages **governance programs** (each with its own fiscal calendar and acknowledgment SLA), the **record classes** and **jurisdictions** that anchor retention rules, the **retention rules** themselves with their revision succession chains, the **records** under governance, the **legal holds** that suspend automated destruction, the **disposition requests** that authorize destruction under counsel review, the **destruction certificates** that document each deletion for future defense, the **hold audits** that measure over-preservation, and the **freeze windows** during which no destruction may proceed. All resources are mounted under a top-level `/ig` prefix. A logical clock — not the wall clock — drives every time-dependent derivation, and an administrator-facing capability advances that clock for testing and for batch operations that must observe a specific "now".

Two themes dominate the design and recur throughout this specification. First, a record's eligibility for destruction is never a stored boolean; it is a derived **disposition posture** that reconciles the governing rule's due date, any active legal hold, and any open retention conflict, recomputed whenever any of those inputs moves. Second, the system is built for defensibility: every destructive act produces an immutable certificate, every approval is segregated from the original requester, every late custodian acknowledgment is recorded, and every hold's staleness and over-preservation cost can be snapshot-audited at any moment.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two HTTP headers: `X-User-ID` (the acting operator's identifier) and `X-User-Role` (the acting role). If either header is missing, empty, or names a role outside the declared set, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role is well-formed but not authorized for the endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The declared roles are exactly five: `PlatformAdmin`, `RecordsManager`, `LegalCounsel`, `Auditor`, and `Custodian`.

When `X-User-Role` is `PlatformAdmin`, `RecordsManager`, `LegalCounsel`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `created_by_user_id` on a `LegalHold`, as `requester_user_id` on a `DispositionRequest`, as `decided_by_user_id` on a decided request, as `resolved_by_user_id` on a resolved `RetentionConflict`, or as `witness_user_id` on a `DestructionCertificate` — but it does not compare the value to any entity's `id`.

When `X-User-Role` is `Custodian`, `X-User-ID` is the `id` of the acting `Custodian` entity. Ownership checks on any resource that references a `Custodian` compare the resource's foreign-key field to `X-User-ID`. Concretely, acknowledging a `HoldCustodian` assignment is permitted only when the assignment's `custodian_id` equals `X-User-ID`; otherwise the request is rejected with `ERR_NOT_CUSTODIAN_OF_ASSIGNMENT` (HTTP 403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, rendered from the server's logical clock (§2.5), not the wall clock.
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
- A request to an undeclared path, or to a declared path with an unsupported method, is rejected with `ERR_NOT_FOUND` (HTTP 404) in this same envelope.

### 2.3. Pagination

All list endpoints accept two query parameters: `limit` (the maximum number of items returned) and `offset` (the number of items skipped before returning results). `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0. Out-of-range or unparseable values are not rejected: an unparseable `limit` or `offset` falls back to its default, and numeric values are clamped into the declared bounds (`limit` into 1–100, `offset` to at least 0). List results are sorted by `created_at` ascending (oldest first), with ties — entities created at the same logical instant — preserving their insertion order. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` indicates whether additional items exist beyond the returned window.

List endpoints also accept exact-match equality filters on the query string: record classes, jurisdictions, and custodians filter by `program_id`; retention rules by `program_id`, `record_class_id`, `jurisdiction_id`, `status`, `supersedes_rule_id`, and `superseded_by_id`; retention conflicts by `program_id`, `status`, `record_class_id`, `jurisdiction_id`, `incumbent_rule_id`, `challenger_rule_id`, and `governing_rule_id`; records by `program_id`, `record_class_id`, `jurisdiction_id`, `owner_custodian_id`, `governing_rule_id`, `status`, and `disposition_posture` (the last validated as an enum); legal holds by `program_id`, `status`, and `custodian_id` (the last matching the holds on which that custodian has an assignment); hold custodian assignments by `hold_id`, `custodian_id`, `status`, and `program_id`; hold scope items by `hold_id`, `record_id`, `status`, and `program_id`; disposition requests by `program_id`, `status`, and `requester_user_id`; disposition items by `request_id`, `record_id`, `status`, and `program_id`; destruction certificates by `program_id`, `record_id`, `request_id`, and `disposition_item_id`; hold audits and disposition freeze windows by `program_id` and `status`; reminder logs by `program_id`, `hold_id`, `hold_custodian_id`, `custodian_id`, and `kind`.

### 2.4. Common Resource Properties and Identifier Discipline

Every persisted entity carries an `id` (a server-minted UUID rendered in the canonical dashed 8-4-4-4-12 hexadecimal form, with no type prefix), a `created_at` timestamp, and — unless explicitly stated otherwise — an `updated_at` timestamp and an integer `version`. Both `created_at` and `updated_at` are ISO 8601 UTC timestamps rendered with three fractional digits. `version` starts at 1 on creation and increments by 1 on every mutation of the entity, including mutations caused by cascades from other entities' transitions; `updated_at` is refreshed whenever the entity mutates.

Two entities deviate from the common-fields baseline. `DestructionCertificate` and `ReminderLog` are append-only records: each carries only `id` and `created_at`; both `updated_at` and `version` are absent on them. Certificates and log entries, once created, are never modified.

URL paths sometimes name multiple resource identifiers (for example, a scope-item exclusion names both the parent hold and the item). Path parameters are validated for existence left-to-right; the first missing identifier yields `ERR_NOT_FOUND` (HTTP 404). Identifiers referenced inside a request body — such as `record_ids`, `custodian_ids`, `record_class_id`, `jurisdiction_id`, `supersedes_rule_id`, or `program_id` — are validated for existence after the path and before domain state checks: a missing record id yields `ERR_REFERENCED_RECORD_NOT_FOUND` (HTTP 404), while a missing non-record entity id yields `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404).

### 2.5. The Logical Clock

Every time-dependent derivation in the system — retention due dates, acknowledgment deadlines, reminder schedules, hold staleness, freeze-window coverage, audit snapshots — reads from a single server-side logical clock. At server startup, before any administrative adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z; it never silently falls back to wall-clock time. A `PlatformAdmin` may advance the logical clock to a supplied instant via a dedicated test-driving capability that accepts `to_iso8601` and returns the new `current_utc`; after such an adjustment, every subsequent read recomputes time-dependent fields (posture, lateness, staleness) against the new clock. Date-only strings supplied for rule windows, record event dates, freeze windows, or the clock-setting capability are interpreted at 00:00:00Z on the named calendar day; full ISO 8601 datetimes retain their stated time and are normalized to UTC (a datetime without an offset is read as UTC).

### 2.6. Optimistic Concurrency Control

Two write endpoints are protected by optimistic concurrency control. Both require a non-optional version field carrying the value the client last observed; a mismatch with the parent entity's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field.

The first protected write is the authoring of a succession rule: a request to supersede an existing active retention rule must carry `expected_retention_rule_version` equal to the target rule's current `version`. The target's `version` legitimately advances whenever a succession head is claimed, so a client holding an older observed version is necessarily working from a stale view of the succession chain and is rejected with `ERR_STALE_VERSION` (HTTP 412).

The second protected write is the release of an issued legal hold: the release request must carry `expected_legal_hold_version` equal to the hold's current `version`. Scope expansion, scope exclusion, custodian addition, and custodian acknowledgment all bump the hold's `version`, so a release decision made against an older observed scope is stale even when the hold's status is still `ISSUED`, and is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.7. Derived and Reconciled State

A record's `disposition_posture` is never persisted as an authoritative column; it is derived on every read from the record's `active_hold_count`, its `retention_due_date`, and the presence of any open retention conflict for its (class, jurisdiction). Several other aggregates are maintained incrementally and reconciled on read: a custodian's `open_obligation_count` counts their assignments in `PENDING` or `ESCALATED`; a hold's `active_scope_count` counts its scope items in `ACTIVE`; a hold's `all_acknowledged` is true exactly when at least one assignment exists and every assignment is in `ACKNOWLEDGED` or `RELEASED`; a hold's `late_ack_count` counts assignments acknowledged late. Whenever any of these inputs change, the dependent aggregates are updated atomically within the same request — every mutation, including multi-entity cascades, is atomic per request.

### 2.8. Validation Ordering

When a single request could violate several rules, checks are evaluated in a fixed priority order so that the surfaced error is deterministic. Authentication context is checked first (missing or malformed `X-User-ID`/`X-User-Role`, then role authorization). Path-parameter existence comes next (left-to-right). Request-body shape follows — a missing required field, type mismatch, or numeric range violation (such as `retention_months` not greater than 0, `size_gb` not greater than 0, `ack_deadline_days` not greater than 0, `monthly_storage_cost_cents_per_gb` not greater than 0, `fiscal_year_end_month` outside 1–12, or a `fiscal_year_end_day` invalid for its month) is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and an enum field carrying a value outside its declared set (across `trigger_basis`, `ack_sla_mode`, `method`, resolution `strategy`, and the `disposition_posture` filter) is rejected with `ERR_INVALID_ENUM_VALUE` (HTTP 400). Then come date-range sanity, minimum-length text rules, non-empty collection requirements, and body-referenced entity existence. Optimistic concurrency checks on `expected_retention_rule_version` or `expected_legal_hold_version` follow, evaluated before domain state checks. State-machine preconditions come after that — attempting an action against a rule not in the required status (for example, activating a rule that is not `DRAFT`, withdrawing one that is not `PENDING_CONFLICT`, or retiring one that is neither `DRAFT` nor `ACTIVE`) is rejected with `ERR_RULE_INVALID_STATE` (HTTP 409), and the parallel state preconditions of the other entities surface as their own domain-specific state errors. Then the disposition freeze window, same-program integrity, uniqueness, held/destroyed record protection, ownership and segregation-of-duties checks, the conflict gate on disposition approval, eligibility gates, the hold-release gate, the APPLY_SHORTEST counsel requirement, the retire-protection rule, and finally the freeze-window overlap rule. Two endpoint families tune this chain: on a hold's scope-expansion and custodian-addition endpoints, validation of the referenced records or custodians (existence, same-program integrity, duplicates, and destroyed-record protection) is evaluated before the hold's state precondition; and on hold creation, destroyed-record protection over the scoped records is evaluated before the `matter_ref` and custodian uniqueness checks.

### 2.9. Program-Scoped Isolation and Immutable Configuration

Every entity other than `GovernanceProgram` itself carries a `program_id` anchoring it to exactly one program. Whenever a request body references other entities — records, custodians, classes, jurisdictions, rules — every referenced entity must belong to the same program as the parent resource or payload; a cross-program reference is rejected with `ERR_CROSS_PROGRAM_REFERENCE` (HTTP 409). Program configuration (`ack_deadline_days`, `reminder_interval_days`, `max_reminders_before_escalation`, `stale_hold_days`, `over_preservation_warn_pct`, `ack_sla_mode`, `fiscal_year_end_month`, `fiscal_year_end_day`) is supplied at program creation and is immutable thereafter.

### 2.10. Precision, Rounding, and Calendar Arithmetic

Monetary quantities are computed in integer cents. The over-preservation percentage is rounded half-up to 2 decimal places. Per-record over-preservation costs are rounded half-up to integer cents per record before summing (sum-then-round is forbidden; see §3.9). Calendar arithmetic is performed at day granularity: a rule's `retention_months` is added to an anchor date via month addition, and when the anchor's day-of-month exceeds the target month's length the result is clamped to the target month's last day (so 2026-01-31 plus one month yields 2026-02-28 in a non-leap year). Retention rule windows use half-open interval semantics — a rule covers event dates `d` where `effective_from` is on or before `d` and either `effective_to` is absent or `d` is strictly before `effective_to`. Disposition freeze windows, by contrast, use closed interval semantics: a window covers the current moment when `start_at` is on or before now and now is on or before `end_at`, and two windows overlap when they share any moment including a shared boundary timestamp.

## 3. Business Logic & Workflows

### 3.1. Establishing the Governance Program and Controlled Vocabularies

A `PlatformAdmin` begins by creating a governance program, supplying `name`, `fiscal_year_end_month` (an integer 1–12), and `fiscal_year_end_day` (a day-of-month valid for the named month, with February accepting a day up to 29). Five operational parameters may optionally be overridden at creation; when omitted they take their defaults. `ack_deadline_days` defaults to 14 and must be greater than 0 — it sets the number of days from hold issuance (or from custodian addition to an already-issued hold) within which each custodian must acknowledge. `reminder_interval_days` defaults to 7 and must be greater than 0 — it is the nominal interval between reminders and is the per-reminder extension under the `REMINDER_ADJUSTED` SLA variant. `max_reminders_before_escalation` defaults to 3 and must be at least 1 — an assignment escalates when its reminder count reaches this threshold. `stale_hold_days` defaults to 180 and must be greater than 0 — it is the inactivity window after which an issued hold counts as stale in audits. `over_preservation_warn_pct` defaults to 20 — an audit's `threshold_breached` flag fires when the computed over-preservation percentage reaches this value (inclusive). `ack_sla_mode` selects between `STRICT` and `REMINDER_ADJUSTED` and defaults to `STRICT`; it governs how custodian lateness is judged at acknowledgment.

Once a program exists, the `PlatformAdmin` registers the controlled vocabularies. Each record class carries `code` (unique within its program), `name`, and `monthly_storage_cost_cents_per_gb` (a fractional-cents storage rate per GB-month, strictly greater than 0, used by over-preservation costing). Each jurisdiction carries `code` (unique within its program) and `name`. Reusing an existing code within the same program is rejected with `ERR_DUPLICATE_CODE` (HTTP 409).

A `RecordsManager` registers custodians with `email` (unique within its program — duplicates yield `ERR_DUPLICATE_CUSTODIAN`), `full_name`, and `department`. A freshly registered custodian's `open_obligation_count` starts at 0; it will climb as hold assignments land and drain as those assignments are acknowledged.

### 3.2. Authoring, Activating, and Succeeding Retention Rules

A `RecordsManager` authors a retention rule by naming its `program_id`, `record_class_id`, `jurisdiction_id`, `rule_code` (unique within the program), `retention_months` (strictly greater than 0), `trigger_basis` (one of `EVENT_DATE` or `FISCAL_YEAR_END`), `effective_from`, and optionally `effective_to`. The effective window is half-open: it covers event dates on or after `effective_from` and strictly before `effective_to`, with an absent `effective_to` meaning the window is open-ended. When `effective_to` is supplied it must be strictly after `effective_from`; otherwise the request is rejected with `ERR_INVALID_DATE_RANGE` (HTTP 400). A new rule is born `DRAFT`. Succession of an existing active rule is never declared on a free-standing creation; it is authored through the dedicated supersede capability.

Activating a `DRAFT` rule (via the activation action on the rule) has two outcomes depending on the surrounding schedule. When the rule declares a `supersedes_rule_id`, the named target must currently be `ACTIVE` — otherwise `ERR_SUPERSEDE_TARGET_NOT_ACTIVE` (HTTP 409) — and the target is superseded first: the target rule's status becomes `SUPERSEDED`, the target's `superseded_by_id` is set to the activating rule, and the target's `version` is incremented by 1. The activating rule then faces the same overlap evaluation as a plain activation against the remaining `ACTIVE` rules of the pair (the just-superseded target excluded): with no remaining overlap it becomes `ACTIVE`; with any remaining undeclared overlap it lands in `PENDING_CONFLICT` and a fresh `OPEN` conflict is spawned against the next overlapping rule by the same selector. When the rule declares no `supersedes_rule_id`, activation checks for any other `ACTIVE` rule covering the same (class, jurisdiction) whose half-open window overlaps this rule's window. Two half-open windows overlap exactly when one's start is strictly before the other's end and the other's start is strictly before the one's end; mere adjacency (one's `effective_from` exactly equal to the other's `effective_to`) is not overlap. With no overlap the rule becomes `ACTIVE`. With an undeclared overlap the activation still succeeds but the rule lands in `PENDING_CONFLICT` instead of `ACTIVE`, and a `RetentionConflict` is created in `OPEN` status with the challenger set to the rule just activated; the incumbent is selected from among the overlapping `ACTIVE` rules by earliest `created_at`, breaking ties by ascending `rule_code`. If a later resolution supersedes that incumbent while further overlapping rules remain, the challenger stays `PENDING_CONFLICT` and a fresh `OPEN` conflict is spawned against the next overlapping rule by the same selector.

Either path of activation — plain or superseding — triggers a recompute cascade over every `ACTIVE`-status record whose (class, jurisdiction) matches: each such record's `retention_due_date`, `governing_rule_id`, and `disposition_posture` are recomputed. For each recomputed record whose posture flipped between `ELIGIBLE` and any of (`RETAINED`, `UNSCHEDULED`, `CONFLICT_BLOCKED`, `HELD`), every `DispositionRequest` in `SUBMITTED` or `APPROVED` containing that record has its `stale_item_count` adjusted — incremented by 1 when the record left `ELIGIBLE`, decremented by 1 when it entered `ELIGIBLE`. This is the mechanism by which rule churn invalidates in-flight disposition batches.

A `PENDING_CONFLICT` challenger may be withdrawn by a `RecordsManager`, returning it to `DRAFT`; the linked `OPEN` conflict becomes `WITHDRAWN`, and records of the contested pair whose posture re-enters `ELIGIBLE` because the conflict cleared cause `stale_item_count` to be decremented by 1 on containing `SUBMITTED`/`APPROVED` requests. A rule may also be retired from `DRAFT` (discarding it) or from `ACTIVE`, moving its `status` to `RETIRED`, but an `ACTIVE` rule may retire only when zero `ACTIVE`-status records carry it as their `governing_rule_id`; otherwise the retirement is rejected with `ERR_RULE_HAS_GOVERNED_RECORDS` (HTTP 409). Destroyed-record tombstones do not block retirement — only live records do. Across every entity, lifecycle position is tracked on a `status` field whose exact UPPERCASE values this section names inline.

Succession of an `ACTIVE` rule is authored through the dedicated supersede capability on the target rule. The author supplies `rule_code`, `retention_months`, `trigger_basis`, `effective_from`, optional `effective_to`, and the OCC field `expected_retention_rule_version` (see §2.6). The new rule is created in `DRAFT` with `supersedes_rule_id` pointing at the target, and `program_id`, `record_class_id`, and `jurisdiction_id` inherited from the target. Creating the successor also increments the target's `version` by 1 — the succession head has been claimed — which is exactly the mutation that another writer's stale `expected_retention_rule_version` check will catch. The new rule is not yet governing; it governs only after it is itself activated, at which point the cascade described above fires.

### 3.3. Resolving Retention Conflicts

An `OPEN` retention conflict names the contested `record_class_id` and `jurisdiction_id`, the `incumbent_rule_id`, and the `challenger_rule_id`. Resolving it (via the resolution action on the conflict) requires the conflict to currently be `OPEN` — otherwise `ERR_CONFLICT_NOT_OPEN` (HTTP 409) — and accepts two inputs: `strategy` and an optional `justification`. The strategy `APPLY_LONGEST` is available to both `RecordsManager` and `LegalCounsel` actors; it selects the rule with the greater `retention_months`. The strategy `APPLY_SHORTEST` is a regulatory downgrade available only to `LegalCounsel` — any other role is rejected with `ERR_SHORTEST_STRATEGY_REQUIRES_COUNSEL` (HTTP 403) — and requires a `justification` of at least 20 characters (shorter text is rejected with `ERR_JUSTIFICATION_TOO_SHORT`, HTTP 400); it selects the rule with the smaller `retention_months`. In either strategy, a tie on `retention_months` is broken first by `created_at` descending (the newer rule wins), then by `rule_code` ascending (lexicographic; never by id).

On resolution the winner becomes or stays `ACTIVE`, the loser becomes `SUPERSEDED` with its `superseded_by_id` set to the winner and its `version` incremented by 1, and the conflict moves to `RESOLVED` with `governing_rule_id`, `resolution_strategy`, `resolution_justification`, and `resolved_by_user_id` recorded. Every record of the contested (class, jurisdiction) then has its `retention_due_date`, `governing_rule_id`, and `disposition_posture` recomputed, with the same `stale_item_count` adjustments on containing `SUBMITTED`/`APPROVED` requests as in rule activation: plus 1 for each record leaving `ELIGIBLE`, minus 1 for each entering `ELIGIBLE`.

### 3.4. Records, Due Dates, and the Disposition Posture Ladder

A `RecordsManager` registers a record under a program by supplying `record_class_id`, `jurisdiction_id`, `title`, `source_system` (an originating-system label such as an email archive), `event_date` (the retention trigger event date, interpreted at 00:00:00Z), `size_gb` (strictly greater than 0; feeds over-preservation costing), and optionally `owner_custodian_id` and `auto_delete_enabled` (defaulting to `true`). At creation the record is `ACTIVE`, and its `retention_due_date` and `governing_rule_id` are computed immediately from the current schedule.

The governing rule for a record is resolved in two steps. First, if any `OPEN` retention conflict exists for the record's (class, jurisdiction), there is no governing rule and the record's posture is `CONFLICT_BLOCKED` (unless a hold outranks it — see below); while a conflict is open the record's `governing_rule_id` reads null, but its `retention_due_date` retains whatever value was last computed for it (null if the record was never scheduled). Otherwise, candidates are `ACTIVE` rules for the same (class, jurisdiction) whose half-open window covers the record's `event_date`. The conflict and withdraw machinery guarantees at most one such candidate for any event date; that candidate is the governing rule, and zero candidates means the record is `UNSCHEDULED` with a null `retention_due_date` and null `governing_rule_id`.

When a governing rule exists, the due date depends on the rule's `trigger_basis`. Under `EVENT_DATE`, the anchor is the record's raw `event_date`. Under `FISCAL_YEAR_END`, the anchor is the first program fiscal-year-end date on or after the `event_date` — the fiscal-year-end for calendar year Y is the date built from the program's `fiscal_year_end_month` and `fiscal_year_end_day` in year Y, clamped to the month's last day when the configured day exceeds that month's length in year Y (a February 29 fiscal-year-end falls on February 28 in a non-leap year), so an `event_date` on or before that year's fiscal-year-end anchors to that same fiscal-year-end (an event exactly on the fiscal-year-end anchors to that same day), and an `event_date` after that year's fiscal-year-end anchors to the following year's. The due date is then the anchor plus the rule's `retention_months`, computed with month arithmetic that clamps to the target month's last day when the anchor's day-of-month exceeds it (so 2026-01-31 plus one month lands on 2026-02-28 in a non-leap year).

A record's `disposition_posture` is derived on read in a pinned precedence order: `UNSCHEDULED` first (no governing rule and no open conflict), then `HELD` (the record's `active_hold_count` is greater than 0), then `CONFLICT_BLOCKED` (an `OPEN` conflict covers its class and jurisdiction), then `ELIGIBLE` (the current logical time is on or after `retention_due_date`, inclusive), else `RETAINED`. The precedence is load-bearing: a record under an active hold reports `HELD` even while its class is mid-conflict.

A `RecordsManager` may correct a record's metadata — `title`, `size_gb`, or `event_date` — through the record-update capability. Every successful update increments the record's `version`, even when the supplied values do not differ from the current ones. Changing `event_date` recomputes `retention_due_date`, `governing_rule_id`, and posture, and triggers the same `stale_item_count` adjustments on containing `SUBMITTED`/`APPROVED` disposition requests as rule churn does. A record whose status is `DESTROYED` can no longer be patched, scoped into a hold, or added to a new disposition request; all three attempts are rejected with `ERR_RECORD_ALREADY_DESTROYED` (HTTP 409).

### 3.5. Issuing, Expanding, and Releasing Legal Holds

A `LegalCounsel` operator creates a legal hold by supplying `program_id`, `matter_ref`, `title`, `reason`, `custodian_ids`, and `record_ids`. Both collections must be non-empty — an empty list is rejected with `ERR_EMPTY_COLLECTION` (HTTP 400). The `matter_ref` must be unique within the program among holds in `DRAFT` or `ISSUED`; a collision is rejected with `ERR_DUPLICATE_MATTER_REF` (HTTP 409). No custodian may appear twice on one hold (rejected with `ERR_DUPLICATE_CUSTODIAN`), and no record may appear twice within one hold's scope or carry status `DESTROYED` (rejected with `ERR_DUPLICATE_SCOPE_RECORD` or `ERR_RECORD_ALREADY_DESTROYED` respectively). The creating operator's `X-User-ID` is recorded as `created_by_user_id`. The hold is born `DRAFT`; each supplied custodian becomes a `HoldCustodian` assignment in `AWAITING_ISSUANCE`, and each supplied record becomes a `HoldScopeItem` in `PENDING_ISSUANCE`.

Issuing a `DRAFT` hold requires at least one scope item in `PENDING_ISSUANCE` and at least one assignment in `AWAITING_ISSUANCE`; a hold lacking either is rejected with `ERR_EMPTY_HOLD_SCOPE` (HTTP 409). On issuance the hold becomes `ISSUED`, `issued_at` and `last_activity_at` are set to the current logical time, and the hold's `version` is incremented by 1. Every `PENDING_ISSUANCE` scope item becomes `ACTIVE` with `activated_at` set; for each item, the record's `active_hold_count` is incremented by 1, its `auto_delete_suspended` is set to `true`, its posture is recomputed, and if its posture left `ELIGIBLE` the containing `SUBMITTED`/`APPROVED` disposition requests have `stale_item_count` incremented by 1. Every `AWAITING_ISSUANCE` assignment becomes `PENDING` with `ack_due_date` set to `issued_at` plus the program's `ack_deadline_days`, and each custodian's `open_obligation_count` is incremented by 1 per newly pending assignment. A `ReminderLog` entry of kind `ISSUED_NOTICE` is written per custodian, with `reminder_seq` set to 0 (the value for non-REMINDER kinds).

While a hold is in `DRAFT`, a `LegalCounsel` may still grow or trim it. Adding custodians to a `DRAFT` hold creates assignments in `AWAITING_ISSUANCE`. Expanding scope on a `DRAFT` hold creates items in `PENDING_ISSUANCE` (no record cascade yet). Removing a scope item from a `DRAFT` hold cancels it outright with no record cascade (it was never `ACTIVE`). Cancelling a `DRAFT` hold wholesale moves it to `CANCELLED`, moves every `PENDING_ISSUANCE` item to `CANCELLED` (again with no record cascade), moves every `AWAITING_ISSUANCE` assignment to `CANCELLED` (with no obligation-count change, since they were never `PENDING`), and writes a `ReminderLog` entry of kind `CANCEL_NOTICE` per custodian.

On an `ISSUED` hold, the same edits are live and heavier. Adding custodians creates assignments directly in `PENDING` with `ack_due_date` set to the current logical time plus the program's `ack_deadline_days`, increments each custodian's `open_obligation_count` by 1, bumps the hold's `version` by 1, and refreshes `last_activity_at`. Expanding scope creates items immediately in `ACTIVE`: for each, the record's `active_hold_count` is incremented by 1, `auto_delete_suspended` set to `true`, posture recomputed, `stale_item_count` incremented by 1 on containing `SUBMITTED`/`APPROVED` requests if the record left `ELIGIBLE`, the hold's `active_scope_count` is recomputed, the hold's `version` is bumped by 1, and `last_activity_at` refreshed. Excluding an `ACTIVE` scope item moves it to `EXCLUDED` with `released_at` set; the record's `active_hold_count` is decremented by 1, `auto_delete_suspended` recomputed (it remains true exactly while `active_hold_count` stays above 0), posture recomputed, `stale_item_count` decremented by 1 if the record entered `ELIGIBLE`, the hold's `active_scope_count` recomputed, the hold's `version` bumped by 1, and `last_activity_at` refreshed. Attempting scope or custodian edits on a hold that is not `DRAFT` or `ISSUED`, or excluding an item that is not `ACTIVE`, is rejected with `ERR_HOLD_INVALID_STATE` (HTTP 409).

Releasing an `ISSUED` hold is the OCC-guarded operation described in §2.6: the request carries `release_reason` (at least 10 characters, else `ERR_JUSTIFICATION_TOO_SHORT`) and `expected_legal_hold_version`, and every custodian assignment must be in `ACKNOWLEDGED` — any assignment still `PENDING` or `ESCALATED` rejects the release with `ERR_HOLD_HAS_UNACKNOWLEDGED_CUSTODIANS` (HTTP 409). On release the hold becomes `RELEASED`, `released_at` and `release_reason` are stored, and the hold's `version` is incremented by 1. Every `ACTIVE` scope item becomes `RELEASED` with `released_at` set; per item the record's `active_hold_count` is decremented by 1, `auto_delete_suspended` recomputed, posture recomputed, and `stale_item_count` decremented by 1 on containing `SUBMITTED`/`APPROVED` requests if the record entered `ELIGIBLE`. Every `ACKNOWLEDGED` assignment becomes `RELEASED` with no change to the custodian's `open_obligation_count` (acknowledged assignments were not counted). A `ReminderLog` entry of kind `RELEASE_NOTICE` is written per custodian.

### 3.6. Custodian Acknowledgment, Reminders, and Escalation

A custodian acknowledges their own assignment via the acknowledgment capability on the assignment. The acting `X-User-ID` must equal the assignment's `custodian_id` (else `ERR_NOT_CUSTODIAN_OF_ASSIGNMENT`), and the assignment must be in `PENDING` or `ESCALATED` (else `ERR_ASSIGNMENT_NOT_ACKNOWLEDGEABLE`, HTTP 409). On acknowledgment the assignment becomes `ACKNOWLEDGED`, `acknowledged_at` is set to the current logical time, and `was_late` is computed per the program's `ack_sla_mode`. Under `STRICT`, the acknowledgment is late exactly when `acknowledged_at` is strictly after the original `ack_due_date` — an acknowledgment exactly at the deadline is on time. Under `REMINDER_ADJUSTED`, the effective deadline is the original `ack_due_date` plus one `reminder_interval_days` per reminder already sent on the assignment (the `reminder_count` at the moment of acknowledgment), and the acknowledgment is late exactly when `acknowledged_at` is strictly after that effective deadline; identical timestamps can therefore flip `was_late` between the two variants. Assignments acknowledged from `ESCALATED` after their due date are always late under both variants. When `was_late` is true, the hold's `late_ack_count` is incremented by 1. The custodian's `open_obligation_count` is decremented by 1, the hold's `all_acknowledged` flag is recomputed, `last_activity_at` is refreshed to the current logical time, and the hold's `version` is incremented by 1.

A `RecordsManager` runs the custodian reminder sweep against a named `program_id`; the sweep returns counts of `reminders_sent` and `escalations_raised`. The sweep visits every assignment in `PENDING` whose `ack_due_date` is strictly before the current logical time. If the assignment's `reminder_count` is still below the program's `max_reminders_before_escalation`, the sweep sends a reminder: `reminder_count` is incremented by 1, `last_reminder_at` is set to now, and a `ReminderLog` entry of kind `REMINDER` is written with `reminder_seq` equal to the new `reminder_count`. If instead the assignment's `reminder_count` has already reached `max_reminders_before_escalation` (inclusive boundary), the assignment escalates: its status becomes `ESCALATED`, `escalated_at` is set to now, and a `ReminderLog` entry of kind `ESCALATION` is written with `reminder_seq` equal to the current `reminder_count`. Note the asymmetry: reminders are a self-loop with a counter, and escalation fires only once the counter has reached the program threshold on a subsequent sweep.

### 3.7. Disposition Requests: From Draft to Decision

A `RecordsManager` creates a disposition request by supplying `program_id`, a non-empty `record_ids` collection (empty yields `ERR_EMPTY_COLLECTION`; any duplicate record id within the request yields `ERR_DUPLICATE_REQUEST_ITEM`, HTTP 409; any already-destroyed record yields `ERR_RECORD_ALREADY_DESTROYED`), a `method` (one of `SECURE_ERASE`, `SHRED`, or `CRYPTO_SHRED` — applied uniformly to every item), and a `justification` of at least 20 characters (shorter yields `ERR_JUSTIFICATION_TOO_SHORT`). The creating operator's `X-User-ID` becomes `requester_user_id`. The request is born `DRAFT` with `stale_item_count` at 0, and each supplied record becomes a `DispositionItem` in `PENDING` with no snapshots yet.

Submitting a `DRAFT` request is restricted to the original requester — any other `X-User-ID` is rejected with `ERR_NOT_REQUEST_OWNER` (HTTP 403) — and requires every item's record to currently be `ELIGIBLE`; the first failing record (in the request's creation order) is named in the `ERR_RECORD_NOT_ELIGIBLE` (HTTP 409) message. On submission the request becomes `SUBMITTED`, `submitted_at` is set, each item captures `snapshot_posture`, `snapshot_due_date`, and `snapshot_hold_count` from its record, and `stale_item_count` is reset to 0. From this moment, any cascade that flips a contained record into or out of `ELIGIBLE` — rule activation, conflict resolution, hold issuance, scope expansion or exclusion, hold release, event-date correction — adjusts `stale_item_count` up or down by 1 per flipping record.

Approval is the exclusive province of `LegalCounsel`, and the approver must not be the original requester: matching `X-User-ID` against `requester_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Approval is also gated three ways, evaluated in a deliberate order. First, no `OPEN` retention conflict may cover any item's (class, jurisdiction) — otherwise `ERR_DISPOSITION_CONFLICT_BLOCKED` (HTTP 409). Second, `stale_item_count` must be 0 — otherwise `ERR_STALE_ELIGIBILITY_SNAPSHOT` (HTTP 409); this is the check that forces a refresh after schedule or hold churn. Third, every item's record must still be `ELIGIBLE` at approval time — otherwise `ERR_RECORD_NOT_ELIGIBLE`. On approval the request becomes `APPROVED` with `decided_at` set to now and `decided_by_user_id` set to the approver's `X-User-ID`.

Rejection is the sibling decision and is deliberately not subject to segregation of duties: any `LegalCounsel` may reject a `SUBMITTED` request, supplying a `rejection_reason` of at least 10 characters (shorter yields `ERR_JUSTIFICATION_TOO_SHORT`). The request becomes `REJECTED` with `decided_at` and `decided_by_user_id` recorded. A rejected request is not terminal: the original requester may return it to `DRAFT` via the revise action, which clears all per-item snapshots (back to null), clears `rejection_reason`, and resets `stale_item_count` to 0; the recorded `decided_at` and `decided_by_user_id` are retained. A `DRAFT` request may also be abandoned entirely via the withdraw action, moving it to `WITHDRAWN`; both revise and withdraw are restricted to the requester with `ERR_NOT_REQUEST_OWNER`.

After churn, the requester can reconcile a `SUBMITTED` request without restarting it via the refresh-snapshots action. Refresh requires the requester identity and that every item's record is currently `ELIGIBLE` (else `ERR_RECORD_NOT_ELIGIBLE`); on success the per-item snapshots are re-captured from current record state and `stale_item_count` is reset to 0. This is the supported path for clearing staleness after a hold is released or a conflict resolved.

### 3.8. Execution and Defensible Deletion Certificates

Executing an `APPROVED` request is performed by a `RecordsManager`. Execution requires the request to be `APPROVED` (else `ERR_REQUEST_INVALID_STATE`, HTTP 409) and requires that no `ACTIVE` disposition freeze window covers the current logical time for the program — if one does, the execution is rejected wholesale with `ERR_DISPOSITION_FREEZE_ACTIVE` (HTTP 409).

Execution processes the request's items one by one in request creation order (the order the `record_ids` were supplied). For each item, the outcome is conditional and skips do not fail the request. If the record is already `DESTROYED` at execution time, the item becomes `SKIPPED_ALREADY_DESTROYED`. Else if the record's posture is not `ELIGIBLE` at execution — typically `HELD` or `CONFLICT_BLOCKED` because a hold or conflict landed between approval and execution — the item becomes `SKIPPED_HELD`. Otherwise the record is destroyed: its status becomes `DESTROYED` with `destroyed_at` set to now, the item becomes `DESTROYED` with its own `destroyed_at`, and a `DestructionCertificate` is written. After all items are processed the request becomes `EXECUTED` with `executed_at` set.

Each destruction certificate is the defensible documentation of a single record's destruction. It captures the `program_id`, the executing `request_id`, the `disposition_item_id`, the destroyed `record_id` (a tombstone reference), and snapshots of `record_title`, `record_class_code`, `jurisdiction_code`, and `retention_due_date` as they stood at destruction. It records the destruction `method` (one of `SECURE_ERASE`, `SHRED`, `CRYPTO_SHRED`), the `destroyed_at` timestamp on the logical clock, a system-generated `content_hash` (a SHA-256 hex digest computed over the record id, the title, and the destruction timestamp), the executing operator's `X-User-ID` as `witness_user_id`, and a `certificate_seq` — a per-program monotonically increasing sequence starting at 1, assigned in destruction order (by `created_at` ascending within a batch). Certificates are immutable and read-only.

The same destruction machinery powers scheduled deletion. A `RecordsManager` runs the auto-deletion sweep against a `program_id` and a destruction `method`; the sweep returns `destroyed_count` and the list of `certificate_ids`. The sweep destroys every record of the program whose posture is `ELIGIBLE`, whose `auto_delete_enabled` is `true`, and whose `auto_delete_suspended` is `false`. An `ACTIVE` freeze window covering the current logical time blocks the sweep wholesale with `ERR_DISPOSITION_FREEZE_ACTIVE`. Within a sweep, records are processed in `created_at` ascending order, with ties broken by `title` ascending (never by id), and each destroyed record produces its certificate with `certificate_seq` assigned in that processing order. Because the sweep runs outside any disposition request, the certificates it writes carry `null` for both `request_id` and `disposition_item_id`.

### 3.9. Hold Audits, Stale Holds, and Over-Preservation

An `Auditor` opens a hold inventory audit against a `program_id`; the audit is born `OPEN` and its snapshot fields are computed once at creation and frozen. The snapshot captures `active_hold_count` (holds currently `ISSUED`), `held_record_count` (program records still in `ACTIVE` status whose posture is `HELD`), `eligible_record_count` (likewise, records whose posture is `ELIGIBLE`), and `over_preserved_record_count` (those `ELIGIBLE` records with `auto_delete_enabled` false); destroyed records are excluded from all record counts.

An issued hold is **stale** when its `last_activity_at` is strictly more than the program's `stale_hold_days` before the audit creation time — activity exactly `stale_hold_days` ago is not stale. A hold's `last_activity_at` is a maintained field: it is null while the hold is an unissued `DRAFT`, is set to the issuance time at issuance, and is thereafter refreshed to the current logical time by custodian addition, scope expansion, and scope-item exclusion (each on an `ISSUED` hold) and by each custodian acknowledgment; hold release and hold cancellation do not refresh it. The audit's `stale_hold_count` counts issued holds meeting this test.

The audit's `over_preservation_pct` is the over-preserved count times 100 divided by the eligible count, rounded half-up to 2 decimal places; when no records are eligible the percentage is 0. The audit's `threshold_breached` flag is true exactly when `over_preservation_pct` reaches the program's `over_preservation_warn_pct` — an inclusive comparison, so a percentage equal to the threshold breaches.

The audit's `over_preservation_cost_cents` is a per-record computation summed with a pinned rounding order. For each over-preserved record, the days over are the floor of the difference between the audit creation time and the record's `retention_due_date` divided by 86,400 seconds; the months over are the floor of the days over divided by 30; the monthly cost is the record's `size_gb` multiplied by its record class's `monthly_storage_cost_cents_per_gb`; and the per-record cost is the monthly cost times the months over, rounded half-up to integer cents. Each per-record cost is rounded first, and only then are the per-record costs summed — summing raw costs and rounding once at the end is forbidden (two records at 41.25 raw cents yield 41 plus 41 equals 82, never 83). When no records are over-preserved the total is 0.

An `Auditor` closes an `OPEN` audit via the close action, which sets `closed_at` and moves the audit to `CLOSED`; the snapshot fields remain frozen as computed at creation. Closing an audit that is not `OPEN` is rejected with `ERR_AUDIT_NOT_OPEN` (HTTP 409).

### 3.10. Freeze Windows and the Notification Trail

A `PlatformAdmin` creates a disposition freeze window by supplying `program_id`, `start_at`, `end_at`, and `reason`. The window is born `ACTIVE` and uses closed-interval semantics: `end_at` must be on or after `start_at` (else `ERR_INVALID_DATE_RANGE`), the window covers the current moment when `start_at` is on or before now and now is on or before `end_at`, and a new window overlaps an existing `ACTIVE` window exactly when one's `start_at` is on or before the other's `end_at` and the other's `start_at` is on or before the one's `end_at` — a shared boundary timestamp counts as overlap and is rejected with `ERR_FREEZE_WINDOW_OVERLAP` (HTTP 409). A freeze window blocks two operations while `ACTIVE`: disposition-request execution and the auto-deletion sweep, both rejected with `ERR_DISPOSITION_FREEZE_ACTIVE`. A `PlatformAdmin` may cancel an `ACTIVE` window, setting `cancelled_at` and moving it to `CANCELLED`; cancelling a non-`ACTIVE` window is rejected with `ERR_FREEZE_WINDOW_NOT_ACTIVE` (HTTP 409).

Every custodian-facing notice is captured in the append-only `ReminderLog`. Each entry carries `program_id`, `hold_id`, `hold_custodian_id`, `custodian_id`, a `kind` drawn from `ISSUED_NOTICE`, `REMINDER`, `ESCALATION`, `RELEASE_NOTICE`, and `CANCEL_NOTICE`, the `sent_at` timestamp on the logical clock, and a `reminder_seq` equal to the assignment's `reminder_count` after the entry — which is 0 for every kind except `REMINDER`. The log is the evidentiary trail that a custodian was notified, reminded, escalated, released, or cancelled, and is queryable by program, hold, assignment, custodian, and kind.

## 4. Endpoint Definitions

All endpoints are mounted under `/ig` except the logical-clock control. Resource-creating endpoints (programs, record classes, jurisdictions, custodians, retention rules including the supersede authoring call, records, legal holds, scope-item expansion, custodian addition, disposition requests, hold audits, freeze windows) return 201 with the created resource; scope-item expansion and custodian addition create a collection per call and return 201 with `response_type` "array" carrying the created scope items or assignments; the scope-item exclusion returns 204 with an empty `data`; all other modifications, decisions, sweeps, and reads return 200.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /ig/programs | Create a governance program (config is immutable after creation) | PlatformAdmin |
| GET | /ig/programs | List governance programs | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| GET | /ig/programs/{programId} | Get a governance program | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| POST | /ig/record-classes | Create a record class | PlatformAdmin |
| GET | /ig/record-classes | List record classes | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| GET | /ig/record-classes/{classId} | Get a record class | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| POST | /ig/jurisdictions | Create a jurisdiction | PlatformAdmin |
| GET | /ig/jurisdictions | List jurisdictions | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| GET | /ig/jurisdictions/{jurisdictionId} | Get a jurisdiction | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| POST | /ig/custodians | Register a custodian | RecordsManager |
| GET | /ig/custodians | List custodians | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| GET | /ig/custodians/{custodianId} | Get a custodian | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| POST | /ig/retention-rules | Author a retention rule (DRAFT); succession is declared via supersede, never here | RecordsManager |
| POST | /ig/retention-rules/{ruleId}/supersede | Author the DRAFT successor of the ACTIVE rule at {ruleId}; OCC on target's version claims the succession head | RecordsManager |
| GET | /ig/retention-rules | List retention rules | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| GET | /ig/retention-rules/{ruleId} | Get a retention rule | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| POST | /ig/retention-rules/{ruleId}/activate | Activate a DRAFT rule; without overlap -> ACTIVE (supersede target -> SUPERSEDED); with undeclared overlap -> PENDING_CONFLICT and an OPEN conflict is created | RecordsManager |
| POST | /ig/retention-rules/{ruleId}/withdraw | Withdraw a PENDING_CONFLICT challenger back to DRAFT; linked conflict -> WITHDRAWN | RecordsManager |
| POST | /ig/retention-rules/{ruleId}/retire | Retire a DRAFT rule, or an ACTIVE rule governing zero records | RecordsManager |
| GET | /ig/retention-conflicts | List retention conflicts | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| GET | /ig/retention-conflicts/{conflictId} | Get a retention conflict | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| POST | /ig/retention-conflicts/{conflictId}/resolve | Resolve an OPEN conflict; APPLY_LONGEST keeps the longer retention, APPLY_SHORTEST the shorter (LegalCounsel only, justification >= 20 chars) | RecordsManager, LegalCounsel |
| POST | /ig/records | Register a record; retention_due_date, governing_rule_id, disposition_posture computed at creation | RecordsManager |
| GET | /ig/records | List records | PlatformAdmin, RecordsManager, LegalCounsel, Auditor |
| GET | /ig/records/{recordId} | Get a record (posture computed on read against the logical clock) | PlatformAdmin, RecordsManager, LegalCounsel, Auditor |
| PATCH | /ig/records/{recordId} | Correct record metadata; event_date change recomputes due date and posture; forbidden once DESTROYED | RecordsManager |
| POST | /ig/legal-holds | Create a legal hold (DRAFT) with initial custodians and record scope | LegalCounsel |
| GET | /ig/legal-holds | List legal holds | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| GET | /ig/legal-holds/{holdId} | Get a legal hold | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| POST | /ig/legal-holds/{holdId}/issue | Issue a DRAFT hold: activates scope (suspends auto-deletion on every scoped record) and starts custodian acknowledgment clocks | LegalCounsel |
| POST | /ig/legal-holds/{holdId}/cancel | Cancel a DRAFT hold; assignments and scope items CANCELLED without record cascades | LegalCounsel |
| POST | /ig/legal-holds/{holdId}/release | Release an ISSUED hold; OCC-guarded; all custodians must have acknowledged | LegalCounsel |
| POST | /ig/legal-holds/{holdId}/scope-items | Expand hold scope with additional records (DRAFT -> PENDING_ISSUANCE; ISSUED -> immediately ACTIVE with full cascade) | LegalCounsel |
| DELETE | /ig/legal-holds/{holdId}/scope-items/{itemId} | Exclude a scope item: DRAFT -> item CANCELLED (no cascade); ISSUED -> item EXCLUDED with reverse cascade | LegalCounsel |
| POST | /ig/legal-holds/{holdId}/custodians | Add custodians to a DRAFT or ISSUED hold; on ISSUED holds assignments start PENDING immediately | LegalCounsel |
| GET | /ig/hold-custodians | List hold custodian assignments | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| GET | /ig/hold-custodians/{assignmentId} | Get a hold custodian assignment | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| POST | /ig/hold-custodians/{assignmentId}/acknowledge | Custodian acknowledges their own assignment (PENDING or ESCALATED -> ACKNOWLEDGED); computes was_late per program ack_sla_mode | Custodian |
| GET | /ig/hold-scope-items | List hold scope items | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| GET | /ig/hold-scope-items/{itemId} | Get a hold scope item | PlatformAdmin, RecordsManager, LegalCounsel, Auditor, Custodian |
| POST | /ig/disposition-requests | Create a disposition request (DRAFT) with per-record items (PENDING, no snapshots until submit) | RecordsManager |
| GET | /ig/disposition-requests | List disposition requests | PlatformAdmin, RecordsManager, LegalCounsel, Auditor |
| GET | /ig/disposition-requests/{requestId} | Get a disposition request | PlatformAdmin, RecordsManager, LegalCounsel, Auditor |
| POST | /ig/disposition-requests/{requestId}/submit | Submit a DRAFT request; captures eligibility snapshots; every record must currently be ELIGIBLE | RecordsManager |
| POST | /ig/disposition-requests/{requestId}/refresh-snapshots | Re-capture eligibility snapshots on a SUBMITTED request; clears stale_item_count | RecordsManager |
| POST | /ig/disposition-requests/{requestId}/approve | Approve a SUBMITTED request; segregation of duties enforced against requester_user_id | LegalCounsel |
| POST | /ig/disposition-requests/{requestId}/reject | Reject a SUBMITTED request with reason | LegalCounsel |
| POST | /ig/disposition-requests/{requestId}/revise | Return a REJECTED request to DRAFT for rework; snapshots and rejection cleared | RecordsManager |
| POST | /ig/disposition-requests/{requestId}/withdraw | Withdraw a DRAFT request | RecordsManager |
| POST | /ig/disposition-requests/{requestId}/execute | Execute an APPROVED request: per-item conditional destruction with certificates; held/conflicted records skipped, already-destroyed records skipped | RecordsManager |
| GET | /ig/disposition-items | List disposition items | PlatformAdmin, RecordsManager, LegalCounsel, Auditor |
| GET | /ig/disposition-items/{itemId} | Get a disposition item | PlatformAdmin, RecordsManager, LegalCounsel, Auditor |
| GET | /ig/destruction-certificates | List destruction certificates (defensible deletion documentation) | PlatformAdmin, RecordsManager, LegalCounsel, Auditor |
| GET | /ig/destruction-certificates/{certificateId} | Get a destruction certificate | PlatformAdmin, RecordsManager, LegalCounsel, Auditor |
| POST | /ig/hold-audits | Open a hold inventory audit; computes snapshot fields including stale holds, over-preservation counts/pct/cost, threshold breach | Auditor |
| GET | /ig/hold-audits | List hold audits | PlatformAdmin, RecordsManager, LegalCounsel, Auditor |
| GET | /ig/hold-audits/{auditId} | Get a hold audit | PlatformAdmin, RecordsManager, LegalCounsel, Auditor |
| POST | /ig/hold-audits/{auditId}/close | Close an OPEN audit; snapshot fields remain as computed at creation | Auditor |
| GET | /ig/reminder-logs | List reminder/notification log entries | PlatformAdmin, RecordsManager, LegalCounsel, Auditor |
| GET | /ig/reminder-logs/{logId} | Get a reminder log entry | PlatformAdmin, RecordsManager, LegalCounsel, Auditor |
| POST | /ig/disposition-freeze-windows | Create a disposition freeze window (CLOSED interval); overlapping an existing ACTIVE window is rejected | PlatformAdmin |
| GET | /ig/disposition-freeze-windows | List disposition freeze windows | PlatformAdmin, RecordsManager, LegalCounsel, Auditor |
| GET | /ig/disposition-freeze-windows/{windowId} | Get a disposition freeze window | PlatformAdmin, RecordsManager, LegalCounsel, Auditor |
| POST | /ig/disposition-freeze-windows/{windowId}/cancel | Cancel an ACTIVE freeze window | PlatformAdmin |
| POST | /ig/sweeps/reminders | Run the custodian reminder sweep: every PENDING assignment strictly past ack_due_date gets a REMINDER or, once reminder_count >= max_reminders_before_escalation, escalates to ESCALATED | RecordsManager |
| POST | /ig/sweeps/auto-delete | Run the auto-deletion sweep: destroys every program record with posture ELIGIBLE, auto_delete_enabled = true, auto_delete_suspended = false; blocked by an ACTIVE freeze window | RecordsManager |
| POST | /_clock/set_current_utc | Set the server logical clock; startup default is exactly 2026-08-01T00:00:00Z and the clock never falls back to wall-clock time | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCED_RECORD_NOT_FOUND | 404 |
| ERR_REFERENCED_ENTITY_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_ENUM_VALUE | 400 |
| ERR_INVALID_DATE_RANGE | 400 |
| ERR_JUSTIFICATION_TOO_SHORT | 400 |
| ERR_EMPTY_COLLECTION | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_RULE_INVALID_STATE | 409 |
| ERR_SUPERSEDE_TARGET_NOT_ACTIVE | 409 |
| ERR_RULE_HAS_GOVERNED_RECORDS | 409 |
| ERR_CONFLICT_NOT_OPEN | 409 |
| ERR_HOLD_INVALID_STATE | 409 |
| ERR_EMPTY_HOLD_SCOPE | 409 |
| ERR_HOLD_HAS_UNACKNOWLEDGED_CUSTODIANS | 409 |
| ERR_REQUEST_INVALID_STATE | 409 |
| ERR_ASSIGNMENT_NOT_ACKNOWLEDGEABLE | 409 |
| ERR_AUDIT_NOT_OPEN | 409 |
| ERR_FREEZE_WINDOW_NOT_ACTIVE | 409 |
| ERR_DUPLICATE_CODE | 409 |
| ERR_DUPLICATE_CUSTODIAN | 409 |
| ERR_DUPLICATE_MATTER_REF | 409 |
| ERR_DUPLICATE_SCOPE_RECORD | 409 |
| ERR_DUPLICATE_REQUEST_ITEM | 409 |
| ERR_FREEZE_WINDOW_OVERLAP | 409 |
| ERR_DISPOSITION_FREEZE_ACTIVE | 409 |
| ERR_RECORD_ALREADY_DESTROYED | 409 |
| ERR_RECORD_NOT_ELIGIBLE | 409 |
| ERR_STALE_ELIGIBILITY_SNAPSHOT | 409 |
| ERR_DISPOSITION_CONFLICT_BLOCKED | 409 |
| ERR_CROSS_PROGRAM_REFERENCE | 409 |
| ERR_NOT_REQUEST_OWNER | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_CUSTODIAN_OF_ASSIGNMENT | 403 |
| ERR_SHORTEST_STRATEGY_REQUIRES_COUNSEL | 403 |
