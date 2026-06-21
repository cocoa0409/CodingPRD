# Contract Lifecycle Management API — Product Requirements Document

## 1. Introduction

Legal and commercial teams spend an enormous amount of effort shepherding a contract from a first draft through negotiation, approval, signature, and the long tail of post-signature obligations and renewals. This document specifies the Contract Lifecycle Management (CLM) API, a multi-tenant backend that brings that entire journey under a single, auditable system of record. The platform maintains a reusable library of clause and contract templates, routes drafts through a quorum-based approval pipeline, captures the back-and-forth of redline negotiation as immutable versions, orchestrates multi-party e-signature, and then tracks the milestones, obligations, and renewal windows that govern a contract once it goes live.

Two cross-cutting disciplines shape the design. The first is **segregation of duties**: the person who drafts or authors a particular redline must never be the one who approves it, and the officer who clears a risky deviation is a different decision seat again. The second is **risk governance**: every version carries a computed risk score derived from how far its clauses stray from the organization's standard language, and a contract that scores at or above its tenant's tolerance cannot be sent for signature until the offending deviations have been formally cleared. Layered on top are optimistic concurrency on the contract aggregate, cascading state propagation between a contract and its children, and a set of scheduled, clock-driven actions — renewal alerts, automatic renewals, expirations, and obligation breaches — that surface only when the logical clock advances.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint. Resources are organized as flat top-level collections (organizations, clause templates, contract templates, contracts, and the various contract sub-resources), each addressable on its own path.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly six roles, spelled precisely as follows: `PlatformAdmin`, `ClauseLibrarian`, `ContractManager`, `ContractApprover`, `RiskOfficer`, and `Signer`. A `PlatformAdmin` is the tenant and clock operator: it provisions organizations and drives the test clock. A `ClauseLibrarian` owns the configuration libraries — clause templates and contract templates. A `ContractManager` drafts and drives contracts: it creates contracts and their versions, submits them for review, sends approved contracts out for signature, renews, terminates, or cancels them, manages obligations, and requests deviation approvals. A `ContractApprover` records approve and reject decisions on approval workflows. A `RiskOfficer` grants or denies deviation approvals. A `Signer` signs or declines signature requests on behalf of an internal or counterparty signatory.

All six roles use an **opaque** identity model. In every case, `X-User-ID` is an operator identifier that is not tied to any persisted entity's `id`; the server never compares it to an entity's `id`. It is, however, recorded where the workflow demands an accountable actor: when a `ContractManager` creates a contract, the caller's `X-User-ID` is stamped onto the contract as `drafter_user_id`; when a `ContractManager` authors an internal redline, it is stamped as `authored_by_user_id` on that version; when a `ContractApprover` records a decision, it is stamped as `approver_user_id` on the step; when a `RiskOfficer` decides a deviation, it is stamped as `decided_by_user_id`; and any event in the audit trail records the causing operator as `actor_user_id`. These recorded identifiers are what the segregation-of-duties checks compare against — they are not entity ownership keys.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. A `limit` outside the range of 1 through 100 is rejected with `ERR_VALIDATION_RANGE`. The `offset` parameter sets how many leading items to skip and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by their `created_at` creation timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning Semantics

Nearly every resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID, with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording first creation. The `updated_at` field, likewise an ISO 8601 UTC timestamp, records the last modification and is refreshed on every mutation. The `version` field is an integer that starts at its initial value and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control (see §2.7).

Two resources are deliberately lighter-weight. An `ApprovalStep` and an `AuditEvent` are write-once records: each carries only an `id` and a `created_at`, and neither has an `updated_at` nor a `version` field. They are never mutated after creation, so those fields are absent by design.

Whenever a derived field on a contract changes — for example its `risk_score`, its `current_version_id`, its `effective_date`, its `expiry_date`, or its `renewal_cycle_index` — that change is a mutation of the contract: it refreshes the contract's `updated_at` and increments the contract's `version`. The same holds for any automatic, server-initiated state transition described in §3; the server may move a resource between states without an explicit client request on that resource, and each such move is a real mutation that bumps `updated_at` and `version` on the affected resource.

### 2.5. Hierarchical Consistency and Cascading State

The `Contract` is the hub of the model, and many of its state changes cascade into the children that hang off it — versions, approval workflows, signature requests, obligations, deviation approvals, and renewal alerts. These cascades are not optional side notes; they are part of the contract of each transition and are enumerated in full in §3. As a general principle, when a contract leaves a stage, the children that were valid only within that stage are resolved in lockstep: superseded versions are marked accordingly, an approval workflow whose pinned version is no longer current is voided, sibling signature requests are voided when one signer declines, open obligations are waived when the contract terminates or expires, and scheduled or due renewal alerts are cancelled or resolved depending on how the contract leaves its active life. Each child mutated in a cascade has its own `version` incremented and its own `updated_at` refreshed.

State can also bubble **up**: a child reaching a decisive state can drive the parent contract's transition. When an approval workflow reaches its quorum it promotes the contract to the approved stage; when the final signature lands it activates the contract; when a signer declines it bounces the contract back into the redline loop. These upward transitions are server-initiated and obey the same versioning rules.

### 2.6. Nested Resource Retrieval and Reference Validation

Many paths address a resource nested under a contract — for example a contract's versions, obligations, or audit events. Path identifiers are validated strictly left-to-right. For any path of the form contract-then-child, the contract identifier is checked first: if no contract with that `id` exists, the request fails immediately with `ERR_CONTRACT_NOT_FOUND` before the child is even consulted. For a path whose leading identifier addresses a non-contract resource — a clause template, contract template, organization, approval workflow, signature request, obligation, deviation approval, or contract version — a missing resource yields `ERR_RESOURCE_NOT_FOUND`.

Before any of these reference or state checks run, every create and action endpoint first validates the shape of its request: all required input fields must be present and well-typed, and any field declared as an enumeration must hold one of its declared members. A missing required field, a value of the wrong type, or an enum value that is not a declared member is rejected with `ERR_INVALID_REQUEST`.

Foreign-key references supplied in a request body are validated separately. On any create endpoint that carries a foreign key in its body, the referenced resource must exist, be of the correct type, and belong to the same organization as the resource being created; otherwise the request fails with `ERR_REFERENCE_NOT_FOUND`. The same error covers the case where a body references a clause that is required to be active but is not.

### 2.7. Optimistic Concurrency on the Contract Aggregate

Several write operations that target a contract guard against acting on a stale view of that contract. These operations require an `expected_contract_version` field in the request body, carrying the `version` value the client last observed for the contract. The server compares `expected_contract_version` against the contract's current `version`; if they differ — because another writer has advanced the contract's `version` since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

Two write paths make this guard especially load-bearing. Submitting a contract for review requires `expected_contract_version` to match the contract's current `version`; if another writer has already created a new version and thereby advanced the contract, the submit is rejected with `ERR_STALE_VERSION` (HTTP 412), because the submitting client's belief about which version it is sending to approval is stale. Likewise, creating a new contract version requires `expected_contract_version` to match the contract's current `version`; a new version legitimately supersedes whatever was current, so a writer working from a stale view is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than being allowed to branch the redline history off a version that is no longer current. The full set of contract write paths that require `expected_contract_version` is: submit, create-version, send-for-signature, terminate, and cancel. Endpoints not in this set take no version field.

### 2.8. Risk Scoring and the Deviation Discipline

Every organization (tenant) declares a `risk_appetite_threshold` — a risk score, from 0 to 100, at or above which a contract may not be sent for signature until its deviations are cleared. If omitted at organization creation, this threshold defaults to 60. A contract's `risk_score` is a computed integer in the range 0 to 100 reflecting how far its current version's clauses depart from the organization's standard language; it is recomputed whenever the current version changes, when the contract is submitted, and when its workflow is approved.

The risk score is built from the current version's `clauses` array. Each clause entry references a clause template by `clause_template_id`, carries the proposed `text`, and an `is_deviation` flag that is true when the proposed text differs from that clause template's `standard_text`. The raw component of the score is the sum, over every clause whose `is_deviation` is true, of the `risk_weight` declared on the referenced `ClauseTemplate`. To this is added a mandatory-miss penalty: for each clause template that the contract's `ContractTemplate` lists in its `clause_template_ids` and marks with `is_mandatory` true, but which is entirely absent from the current version's `clauses` (no entry carries that `clause_template_id`), a penalty of 25 points is added. The risk score is the sum of the raw weight and the mandatory-miss penalty, summed first and then clamped into the range 0 through 100 — a floor of 0 and a ceiling of 100, applied only after the summation.

There are two computation moments that differ **only** in their input set, never in the arithmetic. The **provisional** score is computed at submit time and at version-create time, while the workflow is still pending; its input set includes every clause currently flagged as a deviation, including those whose `DeviationApproval` is still pending. The **final** score is recomputed when the workflow reaches approval; its input set excludes the `risk_weight` of any deviated clause that has a granted `DeviationApproval` pinned to the current version — those deviations count as cleared and no longer add weight — while the mandatory-miss penalty is computed identically in both moments.

### 2.9. Monetary Precision and the Cost Estimate

The system exposes one monetary calculation, a legal-review cost estimate, and it is computed entirely in integer cents — there is no fractional component and no rounding is ever required. The estimate, surfaced as `review_cost_cents`, is described in detail in §3 and is driven solely by the current version's `deviation_count`, independent of any risk weight or deviation-approval status.

### 2.10. The Logical Clock and Scheduled Actions

The system runs against a logical clock that a `PlatformAdmin` advances explicitly. Advancing the clock runs a sweep that processes every time-deferred effect: renewal alerts that have reached their trigger time become due, active contracts whose alerts are due auto-renew or whose terms have run out expire, and obligations whose due dates have passed are breached. Because these effects fire only when the clock is advanced, the precise boundary conditions for each are specified alongside the relevant workflow in §3. All times are ISO 8601 UTC datetimes with millisecond precision preserved.

## 3. Business Logic & Workflows

### 3.1. Building the Library: Clause Templates and Contract Templates

Before any contract can exist, a `ClauseLibrarian` populates the configuration library. A clause template is added to the library for a particular organization, identified by `organization_id`, and is defined by a stable business key `clause_key` (for example `LIABILITY_CAP`), a `category` drawn from the set `LIABILITY`, `INDEMNITY`, `TERMINATION`, `PAYMENT`, `CONFIDENTIALITY`, or `OTHER`, the preferred `standard_text` that serves as the fallback language, and a `risk_weight` expressing the per-clause risk contribution that applies when a contract deviates from that standard text. The `risk_weight` must lie between 0 and 40 inclusive; a value outside that range is rejected with `ERR_VALIDATION_RANGE`. A clause may also be flagged with `is_mandatory`, which defaults to false; when true, a version that drops this clause cannot later be carried to approval. Each clause template carries a `status` that begins at `ACTIVE` and may move to `RETIRED`.

The `clause_key` must be unique among the `ACTIVE` clause templates of the same organization, compared case-sensitively. An attempt to create a clause template whose key already belongs to an active clause of that organization is rejected with `ERR_DUPLICATE_CLAUSE_KEY`. Retiring a clause template moves it from `ACTIVE` to `RETIRED` and increments its `version`; it is permitted only when no contract in a working state — that is, no contract whose `status` is `DRAFT`, `UNDER_REVIEW`, or `REDLINING` — has a current version that still references the clause. Retiring a clause that is still in use that way is refused with `ERR_CLAUSE_IN_USE`.

A contract template composes a standard clause set for an organization. It is created with an `organization_id`, a display `name`, and `clause_template_ids` — an ordered list of clause template identifiers, each of which must belong to the same organization and be `ACTIVE` at the moment the template is created. It also carries a `default_term_months`, defaulting to 12, and an `auto_renew_default` flag, defaulting to false; these are copied onto a contract at creation time when the contract omits the corresponding value. Like a clause template, a contract template's `status` runs from `ACTIVE` to `RETIRED`. Retiring a contract template moves it to `RETIRED` and increments its `version`, and is allowed only when no contract whose `status` is `DRAFT`, `UNDER_REVIEW`, or `REDLINING` references it; otherwise the request is refused with `ERR_TEMPLATE_IN_USE`.

Organizations themselves are provisioned by a `PlatformAdmin`, each with a display `name`, the `risk_appetite_threshold` discussed in §2.8 (default 60, valid range 0 through 100), and an `auto_renew_lead_days` value (default 30, which must be greater than 0) that sets how many days before expiry a renewal alert comes due. A `risk_appetite_threshold` outside 0 through 100, or an `auto_renew_lead_days` of zero or less, is rejected with `ERR_VALIDATION_RANGE`.

### 3.2. Drafting a Contract and the Redline Negotiation Cycle

A `ContractManager` opens a contract in the `DRAFT` state from a chosen contract template. Creation takes an `organization_id`, a `contract_template_id`, a `counterparty_name` naming the other contracting party, and a `title`. The manager may supply `term_months` and `auto_renew`; when either is omitted it is filled from the template's `default_term_months` and `auto_renew_default` respectively. The supplied `term_months`, when present, must be greater than 0, or the request is rejected with `ERR_VALIDATION_RANGE`. On creation the caller's `X-User-ID` is recorded as the contract's `drafter_user_id`, an audit record of type `CONTRACT_CREATED` is appended, and the contract's `current_version_id`, `effective_date`, and `expiry_date` all begin null while `risk_score` begins at 0 and `renewal_cycle_index` at 0.

A contract's substance lives in its versions. Creating a `ContractVersion` supplies the `contract_id`, the `authored_by_party` (either `INTERNAL` or `COUNTERPARTY` — which side produced this redline), the `clauses` array, and the `expected_contract_version` guard. Each entry in `clauses` is an object carrying a `clause_template_id`, the proposed `text`, and the `is_deviation` flag. The server assigns the `version_number` itself, as one greater than the highest existing version number for that contract, so numbering runs 1, 2, 3 and so on. When the author is `INTERNAL`, the caller's `X-User-ID` is stamped as `authored_by_user_id`; for a `COUNTERPARTY` version that field is left null. The server computes `deviation_count` as the number of clause entries whose `is_deviation` is true, sets the contract's `current_version_id` to the new version, and recomputes the contract's `risk_score` provisionally. Every clause's `clause_template_id` must reference an `ACTIVE` clause template belonging to the contract's organization; if not, the version create is rejected with `ERR_REFERENCE_NOT_FOUND`. A freshly created version's `status` is `PROPOSED`.

Submitting a contract moves it from `DRAFT` to `UNDER_REVIEW` (and, after a redline, from `REDLINING` back to `UNDER_REVIEW`). Submission requires that the contract already have a current version — if `current_version_id` is still null, the submit is refused with `ERR_NO_VERSION` — and it requires the `expected_contract_version` guard described in §2.7. The optional `required_approver_count` field sets the quorum for the workflow this submit creates; it must be at least 1 and defaults to 1 if omitted. A successful submit creates a fresh `ApprovalWorkflow` in `PENDING` status, with its `pinned_version_id` set to the contract's `current_version_id`, its `approvals_received` at 0, and its `required_approver_count` copied from the request value or the default. It recomputes `risk_score` provisionally, appends a `SUBMITTED` audit event, and increments the contract's `version`. The current version's own `status` stays `PROPOSED` until the contract actually reaches the approved stage.

The redline cycle is the heart of negotiation. Authoring a new version while the contract is `UNDER_REVIEW` bounces it into `REDLINING`: the prior current version's `status` becomes `SUPERSEDED`, the previously open approval workflow becomes `VOIDED` because its pinned version is no longer current, and any `PENDING` deviation approval whose `contract_version_id` is that now-superseded version is moved to `DENIED` as stale-version compensation. The contract's `current_version_id` advances to the new version and its `risk_score` is recomputed provisionally; a `VERSION_CREATED` audit event is appended, together with a `REDLINE_OPENED` event because the contract was under review, and the contract's `version` is incremented. Resubmitting after a redline closes the cycle: it returns the contract from `REDLINING` to `UNDER_REVIEW`, again creating a fresh `PENDING` workflow pinned to the now-current version, recomputing `risk_score`, appending a `SUBMITTED` event, and incrementing `version`.

A contract may be cancelled by its `ContractManager` while it is `DRAFT` or `REDLINING`, supplying the `expected_contract_version` guard; this carries it to the terminal `CANCELLED` state and increments `version`. When the cancelled contract was in `REDLINING`, any open `PENDING` approval workflow is `VOIDED` as part of the cancellation.

### 3.3. Approval: Quorum, Rejection, and Segregation of Duties

Once a contract is `UNDER_REVIEW`, a `ContractApprover` records decisions against the open `ApprovalWorkflow`. Each decision is an `ApprovalStep` carrying the `approval_workflow_id`, a `decision` of either `APPROVE` or `REJECT`, and an optional `comment`. The acting approver's `X-User-ID` is recorded on the step as `approver_user_id`.

Two checks gate every decision, and their ordering matters. First, segregation of duties is enforced: the caller's `X-User-ID` must differ from the contract's `drafter_user_id` and from the current version's `authored_by_user_id`; a caller who is the drafter or the version author is refused with `ERR_SELF_APPROVAL`. Then, on an `APPROVE` decision that would reach quorum, the mandatory-clause check runs: if the current version omits any clause template that the contract's template marks mandatory, the approval is refused with `ERR_MANDATORY_CLAUSE_MISSING`. The segregation check is evaluated before the mandatory-clause check.

An `APPROVE` decision increments the workflow's `approvals_received`. When `approvals_received` reaches or exceeds the workflow's `required_approver_count`, the workflow moves from `PENDING` to `APPROVED` — provided its `pinned_version_id` is still the contract's `current_version_id`; if a redline had superseded the pinned version the workflow would already have been `VOIDED`. Reaching `APPROVED` bubbles up to carry the contract from `UNDER_REVIEW` to `APPROVED`, at which point the current version's `status` becomes `ACCEPTED`, the contract's `risk_score` is recomputed in its **final** form (clearing granted deviations as described in §2.8), an `APPROVED` audit event is appended, and the contract's `version` is incremented. A `REJECT` decision moves the workflow from `PENDING` to `REJECTED` and bubbles up to bounce the contract from `UNDER_REVIEW` back into `REDLINING`, appending a `REJECTED` audit event; this reopens the negotiation for a new internal version. An approval workflow can also be `VOIDED` by the system whenever a new version supersedes its pinned version or the contract is cancelled.

### 3.4. Clearing Risk: Deviation Approvals

When a version carries deviations that push a contract's risk to or above its organization's appetite, those deviations must be cleared before signature. A `ContractManager` requests a deviation approval against a contract, supplying the `contract_id`, the `contract_version_id` whose deviations the approval clears, the `clause_template_id` of the specific deviated clause it covers, and a `justification` explaining why the deviation is acceptable. A new deviation approval begins in `PENDING` status with `decided_by_user_id` null.

A `RiskOfficer` then decides the request, supplying a `decision` of either `GRANT` or `DENY`. Granting requires two preconditions: the request's `contract_version_id` must still equal the contract's `current_version_id` — if the version has since been superseded, the decide is refused with `ERR_DEVIATION_STALE` — and segregation of duties requires the caller's `X-User-ID` to differ from the contract's `drafter_user_id`, failing otherwise with `ERR_SELF_APPROVAL`. A grant moves the request from `PENDING` to `GRANTED`, stamps the deciding officer as `decided_by_user_id`, appends a `DEVIATION_GRANTED` audit event, and increments the request's `version`. A deny moves it from `PENDING` to `DENIED`, appends a `DEVIATION_DENIED` event, and increments `version`. Beyond an explicit deny, the system itself denies a pending deviation approval as a cascade when the version it covers is superseded by a redline.

### 3.5. Signature: Sending, Signing, and the Join to Active

Sending an `APPROVED` contract for signature is a `ContractManager` action that carries it to `OUT_FOR_SIGNATURE`. The request supplies the `expected_contract_version` guard and a `signers` list describing the parties; the system creates one `SignatureRequest` per signer, each beginning in `SENT` status. Three preconditions gate the send. The risk gate requires either that the contract's `risk_score` be strictly below the organization's `risk_appetite_threshold`, or that every clause template deviated in the current version have a `GRANTED` deviation approval whose `contract_version_id` equals the contract's `current_version_id`; failing this, the send is refused with `ERR_DEVIATION_REQUIRED`. The signer gate requires that the `signers` list contain at least one signer whose side is `INTERNAL` and at least one whose side is `COUNTERPARTY`; an incomplete list is refused with `ERR_SIGNERS_INCOMPLETE`. And the concurrency gate requires the `expected_contract_version` to match, failing with `ERR_STALE_VERSION` otherwise. A successful send appends a `SENT_FOR_SIGNATURE` audit event and increments the contract's `version`.

Each `SignatureRequest` records the `contract_id`, the `signer_party` (`INTERNAL` or `COUNTERPARTY`), and the `signer_name`, with `signed_at` null until signed. A `Signer` signs a request, which is permitted only while the parent contract is `OUT_FOR_SIGNATURE` (otherwise `ERR_INVALID_STATE`); signing sets `signed_at` to the current clock time, moves the request from `SENT` to `SIGNED`, and increments its `version`. Signature is a fork-join: the contract goes live only when every one of its signature requests has reached `SIGNED`. On that final signature, the join fires and the contract moves from `OUT_FOR_SIGNATURE` to `ACTIVE`: its `effective_date` is set to the current clock time, its `expiry_date` is projected from that date, a renewal alert is scheduled, an `ACTIVATED` audit event is appended, and the contract's `version` is incremented.

A `Signer` may instead decline a request, again only while the contract is `OUT_FOR_SIGNATURE`. A decline moves that request from `SENT` to `DECLINED` and bubbles up to bounce the contract from `OUT_FOR_SIGNATURE` back into `REDLINING`; as a cascade, every sibling signature request still in `SENT` is moved to `VOIDED`. Each request's `version` is incremented as it is touched.

### 3.6. Going Live: Term Projection, Obligations, and the Renewal Window

When a contract activates, its `expiry_date` is computed as its `effective_date` plus `term_months` calendar months. Calendar-month addition adds the term to the month component, carrying into years as needed; if the resulting day-of-month does not exist in the target month, the date clamps to the last day of that month — so, for instance, the 31st of a month plus one month lands on the 28th (or 29th) of the following February. The time-of-day component is preserved, and all arithmetic is in UTC. At the same moment, a `RenewalAlert` is created in `SCHEDULED` status with its `trigger_date` set to the contract's `expiry_date` minus the organization's `auto_renew_lead_days` days. The alert is recorded against the contract via `contract_id`, and its `resolution` begins null.

During an `ACTIVE` contract's life, a `ContractManager` defines obligations — commitments such as deliverables or payments. Each `Obligation` carries the `contract_id`, a `description` of what must be done, an `owner_party` (`INTERNAL` or `COUNTERPARTY`) naming who owes it, and a `due_date`. An obligation begins `OPEN` with `completed_at` null. The manager may fulfill an obligation while the parent contract is `ACTIVE` (otherwise `ERR_INVALID_STATE`), which sets `completed_at` to the current clock time, moves it from `OPEN` to `FULFILLED`, and increments its `version`. The manager may also waive an obligation, moving it from `OPEN` to `WAIVED` and incrementing its `version`.

When the clock advances, the sweep evaluates each `SCHEDULED` renewal alert: an alert whose `trigger_date` has been reached — that is, when the current clock time is at or after `trigger_date`, inclusive of the exact boundary instant — and whose parent contract is still `ACTIVE` moves from `SCHEDULED` to `DUE`. The sweep also evaluates obligations: any obligation still `OPEN` whose `due_date` is strictly in the past relative to the current clock time, on a contract that is still `ACTIVE`, moves from `OPEN` to `BREACHED`, and an `OBLIGATION_BREACHED` audit event is appended to the parent contract. A breached obligation is significant because it blocks renewal.

### 3.7. Renewal, Expiry, and Termination

A contract that auto-renews is renewed by the sweep, and one that does not is allowed to expire. When the clock advances on an `ACTIVE` contract whose `auto_renew` is true and which has a `DUE` renewal alert, the contract renews via its self-loop, staying `ACTIVE` with an extended term. A `ContractManager` may also renew manually, supplying the `expected_contract_version` guard; manual renewal requires that a renewal alert with `status` `DUE` exist for the contract (otherwise `ERR_RENEWAL_NOT_DUE`) and that no obligation on the contract be `BREACHED` (otherwise `ERR_OPEN_BREACH`). A renewal increments `renewal_cycle_index` by one, sets the contract's `effective_date` to the prior `expiry_date` so that terms are contiguous with no gap, and recomputes `expiry_date` as that new effective date plus `term_months` calendar months — anchoring on the prior expiry rather than the renewal clock time keeps renewed terms gap-free and order-independent. The `DUE` alert moves to `RESOLVED` with its `resolution` set to `RENEWED`, a new `SCHEDULED` renewal alert is created for the new expiry, a `RENEWED` audit event is appended, and the contract's `version` is incremented.

When the clock reaches or passes an `ACTIVE` contract's `expiry_date` and that contract's `auto_renew` is false, the sweep expires it: the contract moves from `ACTIVE` to the terminal `EXPIRED` state, any renewal alert still `SCHEDULED` or `DUE` is moved to `RESOLVED` with `resolution` `LET_LAPSE`, every obligation still `OPEN` is moved to `WAIVED` because the contract is no longer active, and the contract's `version` is incremented.

A `ContractManager` may terminate an `ACTIVE` contract, supplying the `expected_contract_version` guard, which carries it to the terminal `TERMINATED` state. Termination cascades: every obligation still `OPEN` is moved to `WAIVED`, any renewal alert still `SCHEDULED` or `DUE` is moved to `CANCELLED`, a `TERMINATED` audit event is appended, and the contract's `version` is incremented.

### 3.8. The Cost Estimate, the Audit Trail, and Reading the Record

The legal-review cost estimate is available on demand for a contract's current version. It operates on the current version's `deviation_count` and is priced in a marginal, tiered fashion in integer cents. The estimate always begins from a base of 50000 cents. The first three deviations are each priced at the tier-one rate of 10000 cents; the next five (the fourth through the eighth deviation) are each priced at the tier-two rate of 7500 cents; and every deviation from the ninth onward is priced at the tier-three rate of 5000 cents. Pricing is strictly marginal — each individual deviation is charged at the rate of the tier it falls into, never the whole count at the top tier's rate — so a version with a `deviation_count` of five costs the base plus three units at the tier-one rate plus two units at the tier-two rate. The result, `review_cost_cents`, is the base plus this marginal sum; the response also echoes the `contract_id` and the `deviation_count`.

Every consequential action on a contract leaves a trace in its audit trail. Each `AuditEvent` records the `contract_id` it belongs to, an `event_type` drawn from `CONTRACT_CREATED`, `VERSION_CREATED`, `SUBMITTED`, `REDLINE_OPENED`, `APPROVED`, `REJECTED`, `SENT_FOR_SIGNATURE`, `SIGNED`, `ACTIVATED`, `RENEWED`, `TERMINATED`, `OBLIGATION_BREACHED`, `DEVIATION_GRANTED`, or `DEVIATION_DENIED`, the `actor_user_id` of the operator who caused it (null for system-generated events), and a human-readable `detail` summary stamped when the event is written.

The system is broadly readable across the authorized roles. Contracts can be fetched individually or listed with filters by `organization_id`, `contract_template_id`, `current_version_id`, and `status`. A contract's versions, approval workflows, signature requests, obligations, deviation approvals, renewal alerts, and audit events are each listable under the contract, and individual versions, workflows, and deviation approvals are independently fetchable by `id`. Approval workflows can be listed and filtered by `contract_id`, `pinned_version_id`, and `status`; their steps are listable; deviation approvals can be filtered by `contract_id`, `contract_version_id`, `clause_template_id`, and `status`; obligations by `status` and `owner_party`; and audit events by `event_type`.

### 3.9. Driving the Clock

A `PlatformAdmin` advances the logical clock by supplying a target instant as `to_iso8601`. Setting the clock runs the sweep over all contracts and returns the new clock value as `now_utc` together with the list of affected contracts as `swept_contract_ids`. The sweep applies, in one pass, the scheduled effects described above: renewal alerts whose trigger time has arrived become `DUE`; an `ACTIVE` auto-renewing contract with a `DUE` alert renews on its self-loop, while an `ACTIVE` non-auto-renewing contract whose expiry has arrived expires; and obligations past their due date on still-active contracts breach. This capability exists to make the otherwise time-deferred behavior of the system observable and testable.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including the action endpoints that drive state transitions — return `200 OK`. The request and response payloads for each endpoint are not enumerated here; reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/organizations` | Create an organization (tenant) | PlatformAdmin |
| GET | `/organizations/{id}` | Fetch an organization | PlatformAdmin, ClauseLibrarian, ContractManager, ContractApprover, RiskOfficer |
| POST | `/clause-templates` | Add a clause to the library | ClauseLibrarian |
| GET | `/clause-templates/{id}` | Fetch a clause template | ClauseLibrarian, ContractManager, ContractApprover, RiskOfficer |
| GET | `/clause-templates` | List clause templates | ClauseLibrarian, ContractManager, ContractApprover, RiskOfficer |
| POST | `/clause-templates/{id}/retire` | Retire a clause template | ClauseLibrarian |
| POST | `/contract-templates` | Create a contract template | ClauseLibrarian |
| GET | `/contract-templates/{id}` | Fetch a contract template | ClauseLibrarian, ContractManager, ContractApprover, RiskOfficer |
| GET | `/contract-templates` | List contract templates | ClauseLibrarian, ContractManager, ContractApprover, RiskOfficer |
| POST | `/contract-templates/{id}/retire` | Retire a contract template | ClauseLibrarian |
| POST | `/contracts` | Create a contract in DRAFT from a template | ContractManager |
| GET | `/contracts/{id}` | Fetch a contract | ContractManager, ContractApprover, RiskOfficer, ClauseLibrarian |
| GET | `/contracts` | List contracts | ContractManager, ContractApprover, RiskOfficer |
| POST | `/contracts/{id}/versions` | Create a new contract version (redline) | ContractManager |
| GET | `/contracts/{id}/versions` | List a contract's versions | ContractManager, ContractApprover, RiskOfficer |
| GET | `/contract-versions/{id}` | Fetch a single contract version | ContractManager, ContractApprover, RiskOfficer |
| POST | `/contracts/{id}/submit` | Submit the current version for approval | ContractManager |
| POST | `/contracts/{id}/send-for-signature` | Send an approved contract for signature | ContractManager |
| POST | `/contracts/{id}/renew` | Manually renew an active contract whose alert is due | ContractManager |
| POST | `/contracts/{id}/terminate` | Terminate an active contract | ContractManager |
| POST | `/contracts/{id}/cancel` | Cancel a draft or redlining contract | ContractManager |
| GET | `/contracts/{id}/cost-estimate` | Marginal legal-review cost estimate for the current version | ContractManager, RiskOfficer |
| GET | `/contracts/{id}/approval-workflows` | List a contract's approval workflows | ContractManager, ContractApprover, RiskOfficer |
| GET | `/approval-workflows/{id}` | Fetch an approval workflow | ContractManager, ContractApprover, RiskOfficer |
| GET | `/approval-workflows` | List approval workflows | ContractManager, ContractApprover, RiskOfficer |
| POST | `/approval-workflows/{id}/steps` | Record an approval decision (approve/reject) | ContractApprover |
| GET | `/approval-workflows/{id}/steps` | List a workflow's decision steps | ContractManager, ContractApprover, RiskOfficer |
| GET | `/contracts/{id}/signature-requests` | List a contract's signature requests | ContractManager, ContractApprover, RiskOfficer |
| POST | `/signature-requests/{id}/sign` | Record a signature | Signer |
| POST | `/signature-requests/{id}/decline` | Decline a signature | Signer |
| POST | `/contracts/{id}/obligations` | Create an obligation on a contract | ContractManager |
| GET | `/contracts/{id}/obligations` | List a contract's obligations | ContractManager, ContractApprover, RiskOfficer |
| POST | `/obligations/{id}/fulfill` | Mark an obligation fulfilled | ContractManager |
| POST | `/obligations/{id}/waive` | Waive an obligation | ContractManager |
| POST | `/contracts/{id}/deviation-approvals` | Request a deviation approval | ContractManager |
| GET | `/contracts/{id}/deviation-approvals` | List a contract's deviation approvals | ContractManager, RiskOfficer |
| POST | `/deviation-approvals/{id}/decide` | Grant or deny a deviation | RiskOfficer |
| GET | `/deviation-approvals/{id}` | Fetch a single deviation approval | ContractManager, RiskOfficer |
| GET | `/deviation-approvals` | List deviation approvals | ContractManager, RiskOfficer |
| GET | `/contracts/{id}/renewal-alerts` | List a contract's renewal alerts | ContractManager, RiskOfficer |
| GET | `/contracts/{id}/audit-events` | List a contract's audit trail | ContractManager, ContractApprover, RiskOfficer |
| POST | `/_clock/set_current_utc` | Set the server clock and run the sweep | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NO_VERSION` | 409 Conflict |
| `ERR_SELF_APPROVAL` | 403 Forbidden |
| `ERR_MANDATORY_CLAUSE_MISSING` | 409 Conflict |
| `ERR_DEVIATION_REQUIRED` | 409 Conflict |
| `ERR_DEVIATION_STALE` | 409 Conflict |
| `ERR_SIGNERS_INCOMPLETE` | 409 Conflict |
| `ERR_RENEWAL_NOT_DUE` | 409 Conflict |
| `ERR_OPEN_BREACH` | 409 Conflict |
| `ERR_DUPLICATE_CLAUSE_KEY` | 409 Conflict |
| `ERR_CLAUSE_IN_USE` | 409 Conflict |
| `ERR_TEMPLATE_IN_USE` | 409 Conflict |
| `ERR_VALIDATION_RANGE` | 422 Unprocessable Entity |
