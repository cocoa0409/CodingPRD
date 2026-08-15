# Insurance MGA Program Business API — Product Requirements Document

## 1. Introduction

A managing general agency operates on borrowed paper: a carrier grants the MGA binding authority under a program agreement, and in return expects disciplined underwriting within filed rates, careful stewardship of fiduciary premium funds, transparent bordereaux reporting, and continuous proof — through audits and loss-ratio surveillance — that the book being written is the book that was priced. When that trust breaks down, the carrier's remedies are suspension, run-off, and termination. This platform administers that entire bargain. It governs carrier and TPA onboarding, program proposal and activation, binding-authority guidelines, capacity tranches drawn against a lifetime aggregate, rate and rule filings, policy quoting through issuance and cancellation, premium trust accounting with carrier remittances, claims adjudicated by appointed third-party administrators under capped authority, bordereaux submission and acceptance, carrier audits with remediation and escalation, and loss-ratio evaluations that can suspend a program automatically.

The API is mounted under the `/mga` prefix and is organized around a strict segregation of duties: the MGA's underwriting staff proposes and writes business, the MGA's finance staff moves money and reports it, the carrier's underwriters commit capacity and decide escalations, the carrier's auditors inspect, and TPAs adjust claims within delegated limits. Time in this system is explicit rather than ambient: every window comparison, expiry, lapse, and overdue flag reads a server-side logical clock, and a daily operations checkpoint advances the book's due work in a single deterministic run. This document is the complete product specification; endpoint paths and status codes live in §4, and the error catalogue lives in §5, but the rules that trigger them are distributed through §2 and §3 where they belong to the business narrative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and invariants that apply to every endpoint and every entity in the platform.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The platform recognizes exactly six roles: `PlatformAdmin`, `MGAUnderwriter`, `MGAFinance`, `CarrierUnderwriter`, `CarrierAuditor`, and `TPAAdjuster`. A request missing either header, or carrying a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Every endpoint is further restricted to a declared role set per §4; a request whose role is not permitted for the target endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role and must be implemented exactly. When `X-User-Role` is `CarrierUnderwriter`, `X-User-ID` is the `id` of the acting Carrier; ownership checks on any resource that references a Carrier compare the resource's `carrier_id` foreign key to `X-User-ID` — for example, only the carrier that granted a program may activate, suspend, or terminate it. When `X-User-Role` is `TPAAdjuster`, `X-User-ID` is the `id` of the acting TPA; ownership checks on a claim compare the claim's `assigned_tpa_id` to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `MGAUnderwriter`, `MGAFinance`, or `CarrierAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

The role split mirrors the industry's segregation of duties. A `PlatformAdmin` is the infrastructure operator: it onboards carriers and TPAs, suspends them, and exclusively drives the logical clock and the daily operations checkpoint. An `MGAUnderwriter` proposes programs, drafts guidelines and rate filings, quotes/binds/issues/cancels/reinstates policies, performs final premium audits, reports and reopens claims, and submits audit remediation. `MGAFinance` is the fiduciary desk — premium collections, carrier remittances, and bordereaux drafting/submission — deliberately segregated from underwriting. A `CarrierUnderwriter` activates, suspends, resumes, runs off, terminates, and declines programs; commits and releases capacity; approves, disapproves, and effectuates filings; appoints and manages TPAs; decides referred claims without an authority cap; accepts and rejects bordereaux; and runs loss evaluations. A `CarrierAuditor` schedules audits, conducts them, issues findings, and closes or escalates — organizationally separate from the carrier's underwriting function. A `TPAAdjuster` reviews, reserves, refers, approves (within its delegated authority limit), denies, and pays claims. All six roles may use every read endpoint.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock of §2.5.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses follow this standard envelope format — the 4xx codes of §5's catalogue, plus `ERR_INTERNAL` (HTTP 500) for any unexpected server failure:

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

List endpoints are paginated through query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Non-integer or out-of-range pagination values are rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order, with ties on identical timestamps broken by creation (insertion) sequence. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource — Carrier, TPA, Program, UnderwritingGuideline, CapacityAllocation, RateFiling, Policy, Claim, TPAAppointment, Bordereau, CarrierAudit, and LossEvaluation — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, stamped from the logical clock of §2.5.
- `updated_at` (string): an ISO 8601 UTC timestamp in the same format, refreshed from the same logical clock upon any change to the resource's properties.
- `version` (integer): a system-managed integer that begins at 1 on creation and increments with every mutation of the resource, including mutations produced by cascades — with one exception: a program's derived fields (`trust_balance_cents`, `consumed_aggregate_cents`, `latest_incurred_loss_ratio_pct`) are recomputed in place without incrementing the program's `version` or refreshing its `updated_at` (see §2.10).

The TrustLedgerEntry is the deliberate exception. A ledger entry is an immutable, append-only record: it carries `id` and `created_at` only — both `updated_at` and `version` are absent, and a posted entry can never be modified or deleted. LossEvaluation records are likewise append-only snapshots (created, never transitioned), though they do carry the full common field set. Consistency is immediate: any derived field affected by a mutation — premiums, consumed capacity, trust balances, loss ratios — is recomputed within the same request and visible in that request's response.

### 2.5. The Logical Clock and the Daily Operations Checkpoint

The platform never consults wall-clock time. Every rule in this document that speaks of "the clock" — quote validity, cancellation effectiveness, policy and appointment expiry, filing effectivity, audit windows, reporting deadlines, bordereau overdue flags — reads a server-side logical clock. At server startup the logical clock reads 2026-08-01T00:00:00Z, and it advances only when explicitly set. A `PlatformAdmin` may set the logical clock to a supplied `to_iso8601` instant through a test-driving capability; the response echoes the new `current_utc`.

A second admin-only capability, the daily operations checkpoint, processes the book's due work in a single run. One invocation: completes every policy cancellation whose `cancellation_date` has been reached (moving the policy from `PENDING_CANCELLATION` to `CANCELLED` with the earned-premium, refund, and capacity-release consequences of §3.4); expires every policy in `BOUND` or `ISSUED` whose `effective_to` has passed (moving it to `EXPIRED`); withdraws every quote in `QUOTED` whose `quote_valid_until` has lapsed (moving it to `WITHDRAWN`); expires every appointment in `ACTIVE` whose `effective_to` has passed (moving it to `EXPIRED`); and flags every bordereau still in `DRAFT` whose `due_date` has passed by setting its `overdue` flag to true. The run's response enumerates exactly what it touched, as `cancelled_policy_ids`, `expired_policy_ids`, `withdrawn_quote_ids`, `expired_appointment_ids`, and `flagged_bordereau_ids` — each list holding the touched resources' ids in creation order.

### 2.6. Monetary Precision and Rounding

All monetary values in the platform are integer cents — premiums, limits, reserves, ledger amounts, tranche sizes. Every monetary computation rounds half-up to whole cents at each stated step of its formula; rounding is never deferred to the end of a multi-step calculation, because per-step rounding and end-rounding yield different cents. Loss ratios are the one non-integer quantity: they are percentages rounded half-up to two decimal places, and every threshold comparison against a loss ratio uses the rounded value. Rate factors and percentages supplied as decimal fractions (the program's commission rate, the experience modification factor) preserve their input precision; only the cent amounts derived from them are rounded.

### 2.7. Capacity Accounting: The Lifetime Aggregate and the Current Tranche

Carrier capacity is tracked at two levels, and the levels answer different questions. The **lifetime aggregate** answers "how much of the carrier's paper has this program ever consumed": `aggregate_limit_cents` is granted at program proposal, and `consumed_aggregate_cents` accumulates the gross written premium of every policy in `BOUND`, `ISSUED`, or `PENDING_CANCELLATION`, plus the earned-retained portion of `CANCELLED` policies. Because the aggregate is lifetime written premium, expiry releases nothing, and cancellation returns only the unearned portion — the earned portion stays consumed forever.

The **current tranche** answers "how much capacity is available right now." At most one CapacityAllocation per program may be non-terminal (in `ACTIVE` or `EXHAUSTED` status) at any time. A tranche carries a `period_label` and an `allocated_cents` commitment; its `consumed_cents` starts at zero and grows as policies bind. When consumption reaches the allocation exactly, the tranche flips to `EXHAUSTED`: it still occupies the program's single-allocation slot but accepts no further consumption. A later release that drops consumption back below the allocation flips it to `ACTIVE` again. Creating a replacement tranche supersedes the incumbent (`ACTIVE` or `EXHAUSTED` becomes `SUPERSEDED`), and the unconsumed remainder is reported as released to the carrier; the carrier may also release a tranche outright (to `RELEASED`). Releases floor `consumed_cents` at zero — consumption can never go negative.

### 2.8. Fiduciary Trust Accounting

Premium funds are fiduciary: the MGA holds them in trust for the carrier and the insureds, and the platform enforces that discipline structurally. Each program's trust position, `trust_balance_cents`, is exactly the sum of `amount_cents` over all of its TrustLedgerEntry rows — no other field may diverge from that sum. Four entry types exist, with pinned signs: a `COLLECTION` is positive (premium money in, with the contributing `policy_id` set); a `REFUND` is negative (money returned to an insured, with `policy_id` set); a `CLAIM_PAYMENT` is negative (indemnity out, with `claim_id` set); a `CARRIER_REMITTANCE` is negative (the carrier's share forwarded, with `basis_cents` recording the unremitted-collections basis the remittance was computed from). Every entry also stores `running_balance_cents` — the program's trust balance immediately after that entry posts — and collections and remittances may carry a free-text `memo`. A policy-linked entry moves the policy's `collected_cents` by its signed amount: a `COLLECTION` grows it and a `REFUND` reduces it.

Two fiduciary floors guard the account. A claim payment may never take the trust balance negative. And `min_trust_balance_cents`, fixed at program proposal, is the floor beneath which a remittance may not push the balance. Both rules are stated with their exact triggers in §3.5 and §3.6.

### 2.9. Optimistic Concurrency Control on Program-Superseding Writes

Two write operations replace an incumbent artifact beneath a program and therefore carry optimistic concurrency control against the Program resource: creating an underwriting guideline, and creating a capacity allocation. Each of these requests must carry `expected_program_version`, a non-optional input holding the program `version` the client last observed. Both creates legitimately supersede the prior artifact of their kind and themselves advance the program's `version`, so a client writing from a stale view of the program would supersede blind. If `expected_program_version` does not equal the program's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), and nothing is superseded. No other endpoint in the API takes a version field.

### 2.10. Hierarchical Consistency and Cascading Transitions

Program-level events propagate downward in the same request, and the cascade set is fixed. Suspending a program — whether by direct carrier action, by audit escalation, or by a loss-ratio breach — withdraws every `QUOTED` policy of the program (quotes have consumed no capacity, so nothing is released), suspends every `ACTIVE` TPA appointment, and cancels every `DRAFT` bordereau. The appointment-level suspension itself cascades one level further: every claim assigned to the suspended TPA that is sitting in `UNDER_REVIEW` moves to `REFERRED` with `referral_reason` recorded as `APPOINTMENT_SUSPENDED`. Terminating a program marks all of its guidelines `INACTIVE` and releases its non-terminal tranche to `RELEASED`. Superseding a rate filing withdraws the quotes that were rated under it.

Resumption is deliberately asymmetric: resuming a suspended program does not restore its suspended appointments — the carrier must reinstate each appointment explicitly — and claims referred during the suspension are never auto-returned to the TPA. Every mutation produced by a cascade refreshes the affected resource's `updated_at` and increments its `version`, and the program itself gains a `version` increment on each of its own lifecycle transitions and on each guideline or capacity-allocation create — and on nothing else, per the derived-field exception of §2.4.

### 2.11. Validation Precedence and Nested Resource Retrieval

When a request would violate several rules at once, the first failing check in a fixed evaluation order determines the error returned. The order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role permission and entity-backed ownership (`ERR_FORBIDDEN`); (3) existence of every identifier in the path and every foreign key in the body (`ERR_NOT_FOUND`); (4) body well-formedness — required fields present, types valid, enum members valid, dates parseable, window ordering (`effective_from` strictly before `effective_to` for the half-open windows of filings and policies, while the closed windows of appointments and audit schedules permit the two ends to coincide but never to invert), and amounts positive where required (`ERR_INVALID_REQUEST`); (5) uniqueness constraints (`ERR_NAIC_CODE_EXISTS`, `ERR_LICENSE_NUMBER_EXISTS`); (6) optimistic-concurrency staleness (`ERR_STALE_VERSION`); (7) state legality (`ERR_INVALID_STATE`, `ERR_PROGRAM_TERMINAL`, `ERR_PROGRAM_NOT_ACTIVE`) — with the terminal-program check always evaluated before the merely-not-active check, so a `TERMINATED` or `DECLINED` program yields `ERR_PROGRAM_TERMINAL` rather than the not-active error; (8) safety ceilings and fiduciary floors (authority limits, trust solvency, the trust floor); (9) temporal window rules; (10) business constraints; (11) referential availability; and (12) fiscal reconciliation. An entity in a terminal state rejects every further transition with `ERR_INVALID_STATE` (HTTP 409).

Requests that address nested resources validate path identifiers sequentially from left to right, failing with `ERR_NOT_FOUND` on the first identifier that does not resolve to an existing resource. A request addressed to `/mga/programs/{programId}/policies` under a nonexistent `{programId}` fails for the program before any policy rule is consulted. The same left-to-right discipline applies across every nested path: `{carrierId}` under carriers, `{tpaId}` under TPAs, `{programId}` under programs, and the resource-scoped identifiers `{guidelineId}`, `{allocationId}`, `{filingId}`, `{policyId}`, `{claimId}`, `{appointmentId}`, `{bordereauId}`, `{auditId}`, `{evaluationId}`, and `{entryId}`. Foreign keys in request bodies are validated for existence in the same pass as path identifiers, before any business rule runs.

## 3. Business Logic & Workflows

### 3.1. Onboarding Carriers and Third-Party Administrators

Before any program business can be written, a `PlatformAdmin` onboards the counterparties. A carrier is registered with its legal `name`, its `naic_code`, and a `contact_email`. The `naic_code` is unique across all carriers: an attempt to register a code already on file is rejected with `ERR_NAIC_CODE_EXISTS` (HTTP 409). A new carrier starts in `ACTIVE` status. The carrier-suspension action toggles: invoking it on an `ACTIVE` carrier moves it to `SUSPENDED`, and invoking it on a `SUSPENDED` carrier restores it to `ACTIVE`. Suspension is narrow in scope — a `SUSPENDED` carrier keeps all of its existing programs exactly as they are; the only thing blocked is the activation of new programs.

A third-party administrator is onboarded the same way, with its legal `name`, its adjuster `license_number`, and a `contact_email`. The `license_number` is unique across all TPAs; a duplicate is rejected with `ERR_LICENSE_NUMBER_EXISTS` (HTTP 409). A new TPA starts `ACTIVE`. TPA suspension also toggles, and is likewise narrow: in-flight claims assigned to the TPA and its existing appointments are not cascaded in any way — only the creation of new appointments for that TPA and the activation of pending ones are blocked, surfacing as `ERR_TPA_SUSPENDED` where those workflows require an `ACTIVE` TPA.

### 3.2. Program Proposal, Underwriting Setup, and Carrier Activation

An `MGAUnderwriter` proposes a program by naming the granting `carrier_id` and supplying the program's `name`, its `line_of_business` (one of `COMMERCIAL_AUTO`, `GENERAL_LIABILITY`, `PROPERTY`, `WORKERS_COMPENSATION`, or `PROFESSIONAL_LIABILITY`), the `states_covered` array of US state codes the program may write in, the `inception_date`, the lifetime `aggregate_limit_cents`, the MGA's `commission_rate_pct` expressed as a decimal fraction (0.15 means fifteen percent), two integer percentage thresholds — `corrective_threshold_pct` and `termination_threshold_pct` — that drive loss-ratio outcomes inclusively, the fiduciary floor `min_trust_balance_cents`, and the evidence floor `min_earned_premium_for_ratio_cents` beneath which a loss evaluation reports insufficient data. A new program starts in `PROPOSED` status with `consumed_aggregate_cents` and `trust_balance_cents` at zero, `latest_incurred_loss_ratio_pct` null until the first evaluation runs, and `termination_reason` null.

With the program proposed, the MGA underwriter establishes binding authority. Each UnderwritingGuideline scopes one pairing of `state_code` and `class_code` (for example, California artisans) and carries the binding limits `max_policy_premium_cents` and `max_policy_limit_cents`, plus an optional `min_policy_premium_cents` floor that defaults to zero and is applied by the rating calculation. A new guideline begins in `ACTIVE` status. At most one guideline per scope may be `ACTIVE`: creating a guideline for an already-occupied scope atomically moves the prior `ACTIVE` guideline of that scope to `SUPERSEDED` as part of the same create. Because this create supersedes and also advances the program's `version`, the request must carry `expected_program_version` per the optimistic-concurrency rule of §2.9, failing with `ERR_STALE_VERSION` (HTTP 412) on a mismatch. Guidelines end in `SUPERSEDED` through replacement or in `INACTIVE` through program termination; both are terminal.

In parallel, the carrier underwriter commits capacity. Each CapacityAllocation names a `period_label` (for example, a quarter) and an `allocated_cents` commitment, begins in `ACTIVE` status with `consumed_cents` at zero, and likewise requires `expected_program_version`, rejected with `ERR_STALE_VERSION` when stale. Creating a tranche supersedes the program's current non-terminal tranche — `ACTIVE` or `EXHAUSTED` becomes `SUPERSEDED` — and the superseded tranche's unconsumed remainder is reported as released to the carrier. The carrier may instead release a non-terminal tranche outright, moving it to `RELEASED` and freeing the unconsumed remainder; a manual release requires the acting carrier underwriter's `X-User-ID` to equal the program's `carrier_id`.

Activation is the carrier's gate. Every carrier-scoped program action in this document — activation, suspension, resumption, run-off entry, termination, and decline — requires the acting `CarrierUnderwriter`'s `X-User-ID` to equal the program's `carrier_id`, with any mismatch rejected as `ERR_FORBIDDEN`. The same ownership check guards every other `CarrierUnderwriter` write: capacity commits and releases, filing approval, disapproval and effectuation, appointment activation, suspension, reinstatement and revocation, claim approvals, denials and closures, bordereau acceptance and rejection, and loss evaluations all require the acting carrier to own the program that owns the target resource. Activation moves the program `PROPOSED → ACTIVE` and is permitted only when the carrier itself is `ACTIVE` (a `SUSPENDED` carrier's activation attempt fails with `ERR_INVALID_STATE`), at least one guideline of the program is `ACTIVE`, at least one capacity allocation is `ACTIVE` or `EXHAUSTED`, and at least one rate filing of the program is `EFFECTIVE`. A program that the carrier will not write can instead be declined — `PROPOSED → DECLINED` — recording the supplied `termination_reason`. Both activation and decline increment the program's `version`. `DECLINED` is terminal, and a terminal program rejects any child creation or further transition with `ERR_PROGRAM_TERMINAL`.

### 3.3. Rate Filings: From Draft to Effectivity

Rates, rules, and forms reach the book through filings. An `MGAUnderwriter` drafts a RateFiling for a program by supplying the `state_code` it covers, the `filing_type` (`RATE`, `RULE`, or `FORM`), the `base_rates` map from class code to per-exposure-unit rate in cents, the flat `policy_fee_cents` added to every rated policy, and a half-open effectivity window from `effective_from` (inclusive) to `effective_to` (exclusive). A new filing is `DRAFT` and receives a `version_seq`: a per program-and-state sequence number assigned in creation order, one-based, so the first filing drafted for a program and state is sequence 1. Its `submitted_at` and `approved_at` begin null.

Submission moves a filing `DRAFT → SUBMITTED` and stamps `submitted_at` from the clock; it requires a non-empty `base_rates` map and an `effective_from` strictly earlier than `effective_to`, with either violation rejected as `ERR_INVALID_REQUEST`. The carrier underwriter then decides. Approval (`SUBMITTED → APPROVED`) stamps `approved_at` and enforces window exclusivity within the program and state: no other filing of the same program and `state_code` in `APPROVED` or `EFFECTIVE` status may have a half-open window that intersects this one. Because windows are half-open, adjacency is not intersection — a filing whose `effective_from` is exactly another's `effective_to`, or whose `effective_to` is exactly another's `effective_from`, merely touches the other and is permitted; any true overlap is rejected with `ERR_FILING_WINDOW_OVERLAP`. Disapproval moves the filing to `DISAPPROVED`, from which the MGA underwriter may revise it back to `DRAFT`, resetting `submitted_at` and `approved_at` to null; the draft–submit–disapprove–revise loop is unbounded.

Effectivity is the final carrier act: marking an `APPROVED` filing effective (`APPROVED → EFFECTIVE`) requires the clock to have reached the filing's `effective_from`, failing with `ERR_FILING_NOT_YET_EFFECTIVE` before then. At effectivity, the prior `EFFECTIVE` filing of the same program and state, if one exists, becomes `SUPERSEDED` — and that supersession cascades: every policy still in `QUOTED` whose `filing_id` names the superseded filing is withdrawn (`QUOTED → WITHDRAWN`), while policies already `BOUND` or `ISSUED` keep their original `filing_id` and are never re-rated. If the program itself is terminated or declined, any filing still in `DRAFT` or `SUBMITTED` becomes `WITHDRAWN`; a filer may also abandon a draft by simply never submitting it. `SUPERSEDED` and `WITHDRAWN` are the filing's terminal states.

### 3.4. Quoting, Binding, and the Policy Lifecycle

A policy begins as a quote. An `MGAUnderwriter` quotes a policy under a program by supplying the `insured_name`, the risk `state_code` and `class_code`, the estimated `exposure_units` (at least 1), the requested `coverage_limit_cents`, the policy window from `effective_from` (inclusive) to `effective_to` (exclusive), and optionally an `experience_mod` that defaults to 1.0. Quoting runs a gauntlet in the platform's fixed order (§2.11): state legality first — a terminal program yields `ERR_PROGRAM_TERMINAL` and a non-terminal program that is not `ACTIVE` (still `PROPOSED`, or in `SUSPENDED` or `RUN_OFF`) yields `ERR_PROGRAM_NOT_ACTIVE`; then the temporal check — `effective_from` may not precede the clock, and the policy window must sit inside the half-open window of an `EFFECTIVE` filing for the program and state, failing as `ERR_POLICY_WINDOW_OUTSIDE_FILING` (a failure that presupposes at least one `EFFECTIVE` filing exists for the program and state; when none exists, the window checks are moot and the referential-availability stage below reports `ERR_NO_EFFECTIVE_FILING`); then business constraints — the `state_code` must appear in the program's `states_covered` (`ERR_STATE_NOT_COVERED`), an `ACTIVE` guideline must exist for the state-and-class scope (`ERR_CLASS_NOT_ELIGIBLE`), the computed gross premium must not exceed the guideline's `max_policy_premium_cents` (`ERR_GUIDELINE_PREMIUM_LIMIT`), and `coverage_limit_cents` must not exceed the guideline's `max_policy_limit_cents` (`ERR_GUIDELINE_LIMIT_EXCEEDED`); then referential availability — an `EFFECTIVE` filing must exist for the program and state (`ERR_NO_EFFECTIVE_FILING`) and must carry the class in its `base_rates` (`ERR_CLASS_NOT_FILED`).

The provisional premium is computed from the `EFFECTIVE` filing whose half-open window covers the policy's `effective_from`, using that filing's `base_rates` entry for the policy's `class_code`. The experience modification factor is clamped before it multiplies anything: an `experience_mod` below 0.75 is treated as 0.75, and one above 1.25 as 1.25. The raw premium is the exposure units multiplied by the base rate multiplied by the clamped factor, rounded half-up to whole cents. The flat `policy_fee_cents` is then added, and `gross_premium_cents` is the greater of that sum and the guideline's `min_policy_premium_cents`. The MGA's compensation, `mga_commission_cents`, is the gross premium multiplied by the program's `commission_rate_pct`, rounded half-up to whole cents. The premium ceiling is enforced after this calculation at quote time and re-checked at bind time: a gross above the guideline's `max_policy_premium_cents` is rejected with `ERR_GUIDELINE_PREMIUM_LIMIT`. A created quote records the filing used in `filing_id`, starts in `QUOTED` status with `audit_status` of `NOT_AUDITED`, `collected_cents` and `earned_premium_cents` at zero, `final_premium_cents` null, `capacity_released_cents` zero, `reported_premium_bordereau_id` null, and all of `bound_at`, `issued_at`, `cancelled_at`, `cancellation_date`, `cancellation_reason`, and `pre_cancel_status` null. The quote remains bindable for thirty days: `quote_valid_until` is set to the creation clock plus 30 days.

Binding moves `QUOTED → BOUND` and is where capacity is consumed. The checks run in order: the policy must be `QUOTED` (any other status yields `ERR_INVALID_STATE`); the program must be `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE`); the clock must be no later than `quote_valid_until` (`ERR_QUOTE_EXPIRED`); an `ACTIVE` guideline for the scope must still exist and the gross premium must still fit its premium cap (`ERR_GUIDELINE_PREMIUM_LIMIT`); then the fiscal checks — a non-terminal tranche must exist for the program (`ERR_NO_ACTIVE_ALLOCATION`), the tranche's available capacity (its `allocated_cents` minus its `consumed_cents`) must cover the gross premium (`ERR_TRANCHE_EXHAUSTED`), and the program's aggregate headroom (`aggregate_limit_cents` minus `consumed_aggregate_cents`) must cover it as well (`ERR_CAPACITY_EXCEEDED`). Binding stamps `bound_at` from the clock, adds the gross premium to the tranche's `consumed_cents` — flipping the tranche to `EXHAUSTED` when consumption reaches the allocation exactly — and adds the same amount to the program's `consumed_aggregate_cents`.

Issuance (`BOUND → ISSUED`) is the evidence that money preceded paper: it requires `collected_cents` to be at least `gross_premium_cents`, failing with `ERR_PREMIUM_NOT_COLLECTED` otherwise, and stamps `issued_at`.

Cancellation is a two-step loop, and the policy remembers where it came from. Requesting cancellation on a `BOUND` or `ISSUED` policy moves it to `PENDING_CANCELLATION`; the request carries `cancellation_date` and `reason`, recorded as the policy's `cancellation_date` and `cancellation_reason` (one of `INSURED_REQUEST`, `CARRIER_REQUEST`, or `NON_PAYMENT`), and the requested date may not fall after the policy's `effective_to` (a violation is `ERR_INVALID_REQUEST`). The status held at request time is preserved in `pre_cancel_status` — `BOUND` or `ISSUED` — because reinstatement returns there. The cancellation itself completes at the daily operations checkpoint once the clock reaches `cancellation_date` (`PENDING_CANCELLATION → CANCELLED`): `cancelled_at` is stamped, earned premium is computed as described below, and the refund is the amount by which `collected_cents` exceeds the sum of earned premium and a cancellation fee of 2,500 cents (twenty-five dollars), floored at zero — on a flat cancel the fee is waived entirely. A positive refund posts a `REFUND` ledger entry for its negative amount against the policy. The released capacity, `capacity_released_cents`, is the gross premium minus the earned premium; the tranche's `consumed_cents` and the program's `consumed_aggregate_cents` each drop by that amount (the tranche floored at zero), and an `EXHAUSTED` tranche whose consumption falls below its allocation flips back to `ACTIVE`.

Earned premium follows one formula with two variants. The term is the whole days from `effective_from` to `effective_to` (a term shorter than one whole day counts as one day); the elapsed time is the whole days from `effective_from` to the earlier of the as-of instant and `effective_to`, never negative and never more than the term. The pro-rata earned figure is the gross premium multiplied by the elapsed days and divided by the term days, rounded half-up to whole cents. Three cases select variants: a flat cancel — `cancellation_date` on or before `effective_from` — earns zero and waives the fee; a cancellation requested by the insured (`cancellation_reason` of `INSURED_REQUEST`) that is not flat earns the pro-rata figure grossed up by a factor of 1.10 and rounded half-up to whole cents, a ten-percent penalty that leaves a smaller refund for identical dates; and every other basis — expiry, the earned basis of a loss evaluation, and cancellations for `CARRIER_REQUEST` or `NON_PAYMENT` — earns the plain pro-rata figure.

Reinstatement closes the loop. Only a `CANCELLED` policy may be reinstated — any other status yields `ERR_INVALID_STATE`, evaluated first. A `CANCELLED` policy returns to its `pre_cancel_status` — `CANCELLED → BOUND` or `CANCELLED → ISSUED` — when the program is `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE`), no more than thirty days have passed since `cancelled_at` (`ERR_REINSTATE_WINDOW_CLOSED`), a non-terminal tranche exists (`ERR_NO_ACTIVE_ALLOCATION`), and both the tranche's available capacity and the program's aggregate headroom cover the full `capacity_released_cents` (`ERR_TRANCHE_EXHAUSTED` and `ERR_CAPACITY_EXCEEDED` respectively). Reinstatement re-consumes exactly `capacity_released_cents` from the tranche and the aggregate, clears `cancelled_at`, `cancellation_date`, `cancellation_reason`, and `pre_cancel_status`, and resets `capacity_released_cents` to zero. A `COLLECTION` ledger entry is posted only if a reinstatement premium is actually repaid; otherwise no entry is posted and the earlier cancellation refund stands. A policy returning to `ISSUED` must additionally show `collected_cents` covering `gross_premium_cents` (`ERR_PREMIUM_NOT_COLLECTED`).

The daily checkpoint also ends policies at their natural term: a `BOUND` or `ISSUED` policy whose `effective_to` has passed becomes `EXPIRED`, with `earned_premium_cents` set to the full gross premium — the whole term is earned — and no capacity released, because the aggregate measures lifetime written premium. Quotes die two other deaths beyond expiry of their thirty-day validity: program suspension withdraws them, and supersession of the filing they were rated under withdraws them. `EXPIRED` and `WITHDRAWN` are terminal; `CANCELLED` is not, because of the reinstatement loop.

After the dust settles, the book can be trued up. A final premium audit on a policy in `ISSUED` or `EXPIRED` status whose `audit_status` is still `NOT_AUDITED` — anything else is rejected with `ERR_INVALID_STATE` — takes `actual_exposure_units` and `actual_experience_mod`, runs the identical premium formula on those actuals — re-rated on the policy's original filing (the one recorded in `filing_id`, even if since superseded) with the minimum-premium floor of the scope's currently `ACTIVE` guideline, or zero when none is active — and stores the result as `final_premium_cents`. The delta between final and provisional gross is then settled: a positive delta posts a `COLLECTION` ledger entry for the additional premium, a negative delta posts a `REFUND` entry carrying the negative amount, and both the tranche's `consumed_cents` (floored at zero) and the program's `consumed_aggregate_cents` shift by the delta. If no non-terminal tranche exists at audit time, only the aggregate shifts. The policy's `audit_status` becomes `AUDITED`, and a policy may be final-audited only once.

### 3.5. Premium Collections, Carrier Remittances, and Trust Discipline

Money enters the trust account through collections. `MGAFinance` records a premium collection against a policy with an `amount_cents` and an optional `memo`: the platform posts a `COLLECTION` TrustLedgerEntry for the positive amount with the policy's `policy_id` set, grows the policy's `collected_cents` by the same amount, and grows the program's `trust_balance_cents` by it too, storing the resulting balance as the entry's `running_balance_cents`.

Money leaves for the carrier through remittances, which follow a pinned computation order designed to break the circular-looking dependency between the holdback tier and the remittance. The basis is the sum of the amounts of all `COLLECTION` entries for the program minus the sum of the recorded `basis_cents` of every prior `CARRIER_REMITTANCE` entry — in other words, the collections not yet used to justify a remittance. The MGA's commission on that basis is the basis multiplied by the program's `commission_rate_pct`, rounded half-up to whole cents. Subtracting the commission from the basis yields the net before holdback. The holdback tier keys on that net figure, not on the final remittance: when the net before holdback is at least 100,000 cents (one thousand dollars), the holdback is ten percent of it; otherwise it is two percent — the holdback itself rounded half-up to whole cents. The remittance is the net before holdback minus the holdback.

A remittance request carries `declared_amount_cents` and an optional `memo`, and is validated in the platform's order with two checks worth stating explicitly. The fiduciary-safety check comes first: subtracting the declared amount from `trust_balance_cents` must not push the balance below the program's `min_trust_balance_cents`, failing with `ERR_TRUST_FLOOR_BREACH` (HTTP 422). The fiscal checks follow: if the unremitted-collections basis is zero, there is `ERR_NOTHING_TO_REMIT`; and if `declared_amount_cents` differs from the computed remittance, the request is rejected with `ERR_REMITTANCE_MISMATCH`. A successful remittance posts a `CARRIER_REMITTANCE` entry for the negative amount with its `basis_cents` recorded. Remittances and loss evaluations share a state gate: the program must be in `ACTIVE`, `RUN_OFF`, or `SUSPENDED` — any other non-terminal state yields `ERR_INVALID_STATE`, and a terminal program yields `ERR_PROGRAM_TERMINAL` first, per the precedence rule of §2.11.

### 3.6. Claims Intake, TPA Assignment, and Adjudication

Claims work begins with delegated authority. The carrier underwriter appoints a TPA to a program for a single `claim_type` — one of `PROPERTY_DAMAGE`, `BODILY_INJURY`, `LIABILITY`, or `OTHER` — supplying the `tpa_id`, the `authority_limit_cents` capping the indemnity the TPA may approve without carrier referral, and a closed appointment window from `effective_from` to `effective_to`, both ends inclusive. A new appointment is `PENDING`; the TPA must be `ACTIVE` already, or the create fails with `ERR_TPA_SUSPENDED`. Activation (`PENDING → ACTIVE`) requires the acting carrier underwriter to own the program, and its checks then run in the platform's order: the clock must be no later than `effective_to` (`ERR_APPOINTMENT_WINDOW_CLOSED`); the thirty-day separation from every other appointment of the same program, claim type, and TPA in `ACTIVE` or `SUSPENDED` status must hold — the new window must begin at least thirty days after the other's `effective_to`, or the other's `effective_from` must come at least thirty days after the new window's `effective_to`, and any smaller separation, including windows that merely abut, is a conflict rejected with `ERR_APPOINTMENT_WINDOW_GAP`; and the TPA must be `ACTIVE` (again `ERR_TPA_SUSPENDED`). Distinct TPAs, however, may hold concurrent `ACTIVE` appointments for the same scope; the claim-time selector ranks among them.

An appointment's suspension or revocation pulls its in-flight work upward. Suspending (`ACTIVE → SUSPENDED`) — by direct carrier action or by the program-suspension cascade of §2.10 — refers every claim assigned to that TPA in `UNDER_REVIEW` to `REFERRED` with `referral_reason` recorded as `APPOINTMENT_SUSPENDED`. Reinstating (`SUSPENDED → ACTIVE`) requires the program to be `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE`) and the appointment window still open (`ERR_APPOINTMENT_WINDOW_CLOSED`); referred claims are not auto-returned — they remain `REFERRED` for carrier decision. Revoking an appointment (from `ACTIVE` or `SUSPENDED` to `REVOKED`) is terminal: claims still in `REPORTED` under that TPA remain `REPORTED` but can never start review (`ERR_APPOINTMENT_NOT_ACTIVE`), and revoking from `ACTIVE` additionally refers its `UNDER_REVIEW` claims to `REFERRED` with `APPOINTMENT_SUSPENDED` as the reason. The daily checkpoint expires an `ACTIVE` appointment whose `effective_to` has passed, moving it to `EXPIRED`.

An `MGAUnderwriter` reports a claim against a policy with its `claim_type`, the `occurrence_date`, and the `amount_claimed_cents`. Two temporal guards run first: the occurrence must fall inside the policy term — on or after `effective_from` and strictly before `effective_to` — failing with `ERR_OUTSIDE_COVERAGE_PERIOD`; and the occurrence may be no more than sixty days before the report clock, failing with `ERR_REPORTING_DEADLINE_MISSED`. Assignment then selects the claim's TPA from the program's appointments: the candidate set is every `ACTIVE` appointment of the program whose `claim_type` matches the claim's and whose closed window contains the `occurrence_date`. Candidates are ranked by `authority_limit_cents` descending; ties break by `created_at` ascending and then by the TPA's `license_number` ascending — a business field, never an opaque id. If the candidate set is empty the claim is not created at all, and the report is rejected with `ERR_NO_ELIGIBLE_TPA`. A created claim is `REPORTED`, records the winning appointment's TPA in `assigned_tpa_id`, denormalizes the program into `program_id` for program-scoped queries, and starts with `case_reserve_cents` at zero, `paid_cents` at zero, `reopened_count` at zero, and `approved_amount_cents`, `denial_reason`, `denied_at`, `paid_at`, `referral_reason`, and `reported_claim_bordereau_id` all null.

Adjudication proceeds on assignment-locked ownership: the acting `TPAAdjuster`'s `X-User-ID` must equal the claim's `assigned_tpa_id` for every adjuster action, with mismatches rejected as `ERR_FORBIDDEN`. Starting review moves `REPORTED → UNDER_REVIEW` and requires the appointment under which the claim was assigned to be `ACTIVE`, failing with `ERR_APPOINTMENT_NOT_ACTIVE` otherwise. While `UNDER_REVIEW`, the adjuster may set the `case_reserve_cents` — zero or more — through a self-transition that leaves the status unchanged. The adjuster may also refer the claim to the carrier (`UNDER_REVIEW → REFERRED`), recording `referral_reason` as `ADJUSTER_ESCALATION`; the `referral_reason` field is one of `AUTHORITY_EXCEEDED`, `ADJUSTER_ESCALATION`, or `APPOINTMENT_SUSPENDED`.

Approval is where the authority cap bites. The approved indemnity may never exceed the amount claimed: any `approved_amount_cents` above `amount_claimed_cents` is rejected with `ERR_APPROVED_EXCEEDS_CLAIMED`, for TPA and carrier alike. A TPA adjuster approves only from `UNDER_REVIEW`, only while the assigning appointment is `ACTIVE`, and only within the appointment's `authority_limit_cents` — an approval above that cap is rejected with `ERR_AUTHORITY_LIMIT_EXCEEDED`; the safety ceiling is evaluated before the amount-versus-claimed comparison. The carrier underwriter approves from `UNDER_REVIEW` or `REFERRED` and is bound by no authority cap. Approval sets `approved_amount_cents`. Denial mirrors the shape: from `UNDER_REVIEW` by the assigned TPA (appointment `ACTIVE`) or the carrier, and from `REFERRED` by the carrier only, moving the claim to `DENIED`; a non-empty `denial_reason` is required, the reason is stored, and `denied_at` is stamped from the clock.

Payment moves `APPROVED → PAID` and is an adjuster action with a fiduciary guard: the program's `trust_balance_cents` must be at least the `approved_amount_cents`, failing with `ERR_TRUST_INSUFFICIENT_FUNDS` — fiduciary funds may never go negative. Payment posts a `CLAIM_PAYMENT` ledger entry for the negative approved amount with the `claim_id` set, sets the claim's `paid_cents` to the approved amount, stamps `paid_at`, and zeroes `case_reserve_cents`.

A denied claim gets a bounded second chance. An `MGAUnderwriter` may reopen a `DENIED` claim (`DENIED → REOPENED`) at most twice — a claim whose `reopened_count` has already reached 2 is rejected with `ERR_REOPEN_LIMIT_EXCEEDED` — and only within ninety days of `denied_at`, failing with `ERR_REOPEN_WINDOW_CLOSED` after that; the ninety-day window is evaluated before the two-reopen cap. Each reopen increments `reopened_count`, and the assigned TPA then resumes review (`REOPENED → UNDER_REVIEW`), again requiring the assigning appointment to be `ACTIVE` (`ERR_APPOINTMENT_NOT_ACTIVE`). The deny–reopen–review loop is bounded by the two-reopen cap. Closure is the carrier's final act: a claim in `PAID` or `DENIED` moves to `CLOSED`, which is terminal.

### 3.7. Bordereaux Reporting and Data Quality

Bordereaux are the program's reporting lifeblood to the carrier, and the platform treats their data quality as a hard gate. `MGAFinance` drafts a Bordereau with a `bordereau_type` (`PREMIUM` or `CLAIMS`), a `period_label` such as a year-month, the carrier's contractual `due_date`, an optional `rows` array that defaults to empty, and optional `declared_totals`; its `overdue` flag starts false. A `PREMIUM` row carries a `policy_id`, the `written_premium_cents`, and the `commission_cents`; a `CLAIMS` row carries a `claim_id`, the `paid_cents`, and the `case_reserve_cents`. The declared totals for `PREMIUM` are `premium_cents` and `commission_cents`; for `CLAIMS` they are `paid_cents` and `reserve_cents`. The server maintains `computed_totals` and `row_count` on the draft: for `PREMIUM` bordereaux, each row's commission is recomputed as that row's written premium multiplied by the program's `commission_rate_pct`, rounded half-up to whole cents, and the commission total is the sum of those per-row rounded figures — the per-row rounding happens before summation, pinned, because summing unrounded amounts and rounding once yields different cents and is wrong; the premium total is the plain sum of the rows' written premiums. For `CLAIMS` bordereaux the totals are plain sums of the rows' paid and reserve amounts. A draft may legitimately hold zero rows while it is being assembled.

Submission (`DRAFT → SUBMITTED`) is where quality is enforced, in this order: the bordereau must contain at least one row (`ERR_EMPTY_BORDEREAU`); no other bordereau of the same program, `bordereau_type`, and `period_label` may already be `ACCEPTED` (`ERR_BORDEREAU_PERIOD_COVERED`); no `policy_id` (on a `PREMIUM` bordereau) or `claim_id` (on a `CLAIMS` bordereau) may repeat within `rows` (`ERR_BORDEREAU_DUPLICATE_ROW`); every referenced policy or claim must exist and belong to this program (`ERR_BORDEREAU_ROW_UNKNOWN_POLICY`); every row's amounts must equal the referenced entity's current fields — for `PREMIUM`, the policy's `gross_premium_cents` and `mga_commission_cents`, for `CLAIMS`, the claim's `paid_cents` and `case_reserve_cents` (`ERR_BORDEREAU_ROW_MISMATCH`); and `declared_totals` must equal `computed_totals` exactly (`ERR_BORDEREAU_TOTAL_MISMATCH`). Submission stamps `submitted_at` from the clock and freezes `computed_totals` and `row_count`.

The carrier underwriter then dispositions the submission. Acceptance (`SUBMITTED → ACCEPTED`) marks the underlying records as reported: on a `PREMIUM` bordereau each referenced policy's `reported_premium_bordereau_id` is set to the accepting bordereau, and on a `CLAIMS` bordereau each referenced claim's `reported_claim_bordereau_id`. Rejection (`SUBMITTED → REJECTED`) requires a non-empty `rejection_reason`, which is stored. The MGA finance desk may revise a rejected bordereau back to `DRAFT`, clearing `rejection_reason` and resetting `submitted_at` to null; the draft–submit–reject–revise loop is unbounded. A draft may be cancelled outright (`DRAFT → CANCELLED`), and program suspension cancels drafts automatically. Finally, a bordereau still in `DRAFT` whose `due_date` has passed is flagged `overdue` at the next daily operations checkpoint. `ACCEPTED` and `CANCELLED` are terminal.

### 3.8. Carrier Audits, Loss-Ratio Surveillance, and Program Wind-Down

The carrier's audit function inspects the MGA's stewardship. A `CarrierAuditor` schedules an audit with a `scope` of `UNDERWRITING`, `CLAIMS`, `TRUST_ACCOUNTING`, or `FULL`, plus a `scheduled_start` and `scheduled_end` (`scheduled_start` may not fall after `scheduled_end`; the two may coincide). The new audit is `SCHEDULED`, with `outcome` null until closure or escalation sets it, and its window must sit at least thirty days clear of every non-terminal audit of the same program — one in `SCHEDULED`, `IN_PROGRESS`, `FINDINGS_ISSUED`, or `REMEDIATION` — measured in either direction between the scheduled windows; a tighter spacing is rejected with `ERR_AUDIT_WINDOW_GAP`. Starting the audit (`SCHEDULED → IN_PROGRESS`) requires the clock to have reached `scheduled_start`, failing with `ERR_AUDIT_WINDOW_NOT_OPEN` before then.

Issuing findings moves the audit `IN_PROGRESS → FINDINGS_ISSUED` and stores the supplied `findings`; each finding is stored as exactly a `finding_id`, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, a `description` (a string, which may be null), and a `resolved` flag defaulting to false when omitted, and the array may be empty for a clean audit. The MGA underwriter answers with remediation (`FINDINGS_ISSUED → REMEDIATION`), supplying `resolved_finding_ids`; every finding whose `finding_id` appears in that list is marked with `resolved` set to true. The auditor closes from either `FINDINGS_ISSUED` or `REMEDIATION` into `CLOSED`, setting the `outcome` from the request — `SATISFACTORY`, `CORRECTIVE_ACTION`, or `TERMINATION_RECOMMENDED` — but closure is barred while any finding of `MAJOR` or `CRITICAL` severity remains unresolved, failing with `ERR_UNRESOLVED_CRITICAL_FINDINGS`.

Escalation is the audit's teeth. From `FINDINGS_ISSUED` or `REMEDIATION`, the auditor may escalate to `ESCALATED`, but only when at least one `CRITICAL` finding remains unresolved — otherwise the attempt fails with `ERR_NO_CRITICAL_FINDING`. Escalation sets the audit's `outcome` to `TERMINATION_RECOMMENDED` and, if the program is `ACTIVE`, suspends it on the spot, firing the full suspension cascade of §2.10: quotes withdrawn, appointments suspended with their under-review claims referred, and draft bordereaux cancelled. `CLOSED` and `ESCALATED` are the audit's terminal states.

Between audits, the loss ratio keeps watch. A `CarrierUnderwriter` runs a loss evaluation for a program by supplying a `period_label`; the snapshot records the program's earned premium, paid losses, and case reserves, and derives two ratios. The earned basis, `earned_premium_cents`, is the sum of the pro-rata earned premium — computed per §3.4's earned-premium rule as of the evaluation clock, except that a `CANCELLED` policy contributes the earned premium crystallized at its cancellation (its variant already applied) — over the program's policies in `ISSUED`, `PENDING_CANCELLATION`, `CANCELLED`, or `EXPIRED`. The paid basis, `paid_losses_cents`, is the sum of `paid_cents` over the program's claims in `PAID` or `CLOSED` whose `paid_at` is no later than the clock. The reserve basis, `case_reserves_cents`, is the sum of `case_reserve_cents` over claims in `REPORTED`, `UNDER_REVIEW`, `REFERRED`, `APPROVED`, or `REOPENED`. From these, `paid_loss_ratio_pct` is the paid losses multiplied by 100 and divided by the earned premium, rounded half-up to two decimal places, and `incurred_loss_ratio_pct` is the sum of paid losses and case reserves treated the same way; when the earned basis is zero, both ratios are null.

The `outcome` turns the ratios into consequences, with inclusive thresholds compared against the rounded incurred ratio. When the earned basis falls below the program's `min_earned_premium_for_ratio_cents`, the outcome is `INSUFFICIENT_DATA`. When the earned basis is zero the ratios are null, and if the evidence floor is also zero — so the basis is not below it — the null ratios breach no threshold and the outcome is `OK`. Otherwise, an incurred ratio at or above `termination_threshold_pct` yields `TERMINATION_REVIEW`; failing that, an incurred ratio at or above `corrective_threshold_pct` yields `CORRECTIVE_ACTION`; anything lower yields `OK`. The paid-basis ratio is informational only — for identical data it never exceeds the incurred basis and may clear thresholds the incurred basis breaches — and only the incurred basis drives outcomes. The program's `latest_incurred_loss_ratio_pct` updates to the new incurred figure on every evaluation. A `TERMINATION_REVIEW` outcome auto-suspends the program, firing the same full suspension cascade as an audit escalation.

When a book stops performing or a relationship ends, the carrier winds the program down deliberately. Entering run-off (from `ACTIVE` or `SUSPENDED` into `RUN_OFF`) stops new business — new policy quotes and binds are rejected with `ERR_PROGRAM_NOT_ACTIVE` — while in-force policies simply continue to expiry. Termination (`RUN_OFF → TERMINATED`) is the final accounting, and the carrier supplies the `termination_reason`; it is permitted only when no policy of the program remains in `QUOTED`, `BOUND`, `ISSUED`, or `PENDING_CANCELLATION` (`ERR_PROGRAM_HAS_ACTIVE_POLICIES`), no claim remains in `REPORTED`, `UNDER_REVIEW`, `REFERRED`, `APPROVED`, or `REOPENED` (`ERR_OPEN_CLAIMS_EXIST`), no bordereau remains in `DRAFT`, `SUBMITTED`, or `REJECTED` (`ERR_UNACCEPTED_BORDEREAUX`), and the trust balance is exactly zero (`ERR_TRUST_NOT_ZERO`). Termination marks every guideline of the program `INACTIVE`, releases the non-terminal tranche to `RELEASED`, and records the `termination_reason`. Resuming a suspended program (`SUSPENDED → ACTIVE`) is its mirror: it requires that no audit of the program sits in `ESCALATED` with an unresolved `CRITICAL` finding (failing with `ERR_INVALID_STATE` otherwise), and it restores none of the suspended appointments — the carrier reinstates each explicitly. `TERMINATED` and `DECLINED` are terminal; a terminal program rejects any child creation or further transition with `ERR_PROGRAM_TERMINAL`, and that check is evaluated before any not-active check so terminal programs always yield the terminal error.

## 4. Endpoint Definitions

Operations that create a new resource — onboarding a carrier or TPA, proposing a program, adding a guideline, tranche, filing, policy, appointment, bordereau, audit, or loss evaluation to a program, reporting a claim, recording a collection or remittance — return `201 Created`. Operations that act on an existing resource — every state transition and every read — return `200 OK`. List endpoints accept the pagination parameters `limit` and `offset` (§2.3) plus the optional filters named per resource below: `status` on most collections, `carrier_id` on programs, `program_id` on cross-program collections, `state_code` on filings, `filing_id` on policies, `tpa_id` on appointments, `assigned_tpa_id` and `policy_id` on claims, `claim_id` and `entry_type` on trust ledger entries, and `bordereau_type` on bordereaux. Request payloads, computed fields, and side effects are specified by the narratives of §2 and §3 rather than restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mga/carriers` | Onboard a carrier | PlatformAdmin |
| GET | `/mga/carriers/{carrierId}` | Get a carrier | Any authenticated role |
| GET | `/mga/carriers` | List carriers (filter: `status`) | Any authenticated role |
| POST | `/mga/carriers/{carrierId}/suspend` | Toggle carrier `ACTIVE` ↔ `SUSPENDED`; suspension blocks new program activations | PlatformAdmin |
| POST | `/mga/tpas` | Onboard a TPA | PlatformAdmin |
| GET | `/mga/tpas/{tpaId}` | Get a TPA | Any authenticated role |
| GET | `/mga/tpas` | List TPAs (filter: `status`) | Any authenticated role |
| POST | `/mga/tpas/{tpaId}/suspend` | Toggle TPA `ACTIVE` ↔ `SUSPENDED`; suspension blocks new appointments | PlatformAdmin |
| POST | `/mga/programs` | Propose a program under a carrier (created `PROPOSED`) | MGAUnderwriter |
| GET | `/mga/programs/{programId}` | Get a program (includes computed `consumed_aggregate_cents`, `trust_balance_cents`) | Any authenticated role |
| GET | `/mga/programs` | List programs (filters: `carrier_id`, `status`) | Any authenticated role |
| POST | `/mga/programs/{programId}/activate` | Carrier activates program (`PROPOSED` → `ACTIVE`) | CarrierUnderwriter |
| POST | `/mga/programs/{programId}/suspend` | Carrier suspends program; cascades to quotes, appointments, claims, bordereaux | CarrierUnderwriter |
| POST | `/mga/programs/{programId}/resume` | Carrier resumes a suspended program | CarrierUnderwriter |
| POST | `/mga/programs/{programId}/enter-runoff` | Carrier places program into run-off (no new business) | CarrierUnderwriter |
| POST | `/mga/programs/{programId}/terminate` | Carrier terminates a run-off program after full wind-down | CarrierUnderwriter |
| POST | `/mga/programs/{programId}/decline` | Carrier declines a proposed program | CarrierUnderwriter |
| POST | `/mga/programs/{programId}/guidelines` | Create/replace the binding-authority guideline for a (state, class) scope; supersedes the prior `ACTIVE` guideline of the same scope | MGAUnderwriter |
| GET | `/mga/programs/{programId}/guidelines` | List guidelines of a program (filter: `status`) | Any authenticated role |
| GET | `/mga/guidelines/{guidelineId}` | Get a guideline | Any authenticated role |
| GET | `/mga/guidelines` | List guidelines across programs (filters: `program_id`, `status`) | Any authenticated role |
| POST | `/mga/programs/{programId}/capacity-allocations` | Carrier commits a capacity tranche; supersedes the current non-terminal tranche | CarrierUnderwriter |
| GET | `/mga/programs/{programId}/capacity-allocations` | List capacity allocations of a program (filter: `status`) | Any authenticated role |
| GET | `/mga/capacity-allocations/{allocationId}` | Get a capacity allocation | Any authenticated role |
| GET | `/mga/capacity-allocations` | List capacity allocations across programs (filters: `program_id`, `status`) | Any authenticated role |
| POST | `/mga/capacity-allocations/{allocationId}/release` | Carrier releases unconsumed tranche capacity | CarrierUnderwriter |
| POST | `/mga/programs/{programId}/rate-filings` | Draft a rate/rule/form filing (`DRAFT`) | MGAUnderwriter |
| GET | `/mga/programs/{programId}/rate-filings` | List filings of a program (filters: `state_code`, `status`) | Any authenticated role |
| GET | `/mga/rate-filings/{filingId}` | Get a filing | Any authenticated role |
| GET | `/mga/rate-filings` | List filings across programs (filters: `program_id`, `state_code`, `status`) | Any authenticated role |
| POST | `/mga/rate-filings/{filingId}/submit` | Submit filing (`DRAFT` → `SUBMITTED`) | MGAUnderwriter |
| POST | `/mga/rate-filings/{filingId}/approve` | Carrier approval (`SUBMITTED` → `APPROVED`); window-overlap check | CarrierUnderwriter |
| POST | `/mga/rate-filings/{filingId}/disapprove` | Disapprove filing (`SUBMITTED` → `DISAPPROVED`) | CarrierUnderwriter |
| POST | `/mga/rate-filings/{filingId}/revise` | Return a disapproved filing to `DRAFT` for rework | MGAUnderwriter |
| POST | `/mga/rate-filings/{filingId}/mark-effective` | Activate filing (`APPROVED` → `EFFECTIVE`); supersedes prior `EFFECTIVE` filing, withdrawing its `QUOTED` policies | CarrierUnderwriter |
| POST | `/mga/programs/{programId}/policies` | Quote a policy (`QUOTED`); computes the provisional premium from the `EFFECTIVE` filing | MGAUnderwriter |
| GET | `/mga/programs/{programId}/policies` | List policies of a program (filter: `status`) | Any authenticated role |
| GET | `/mga/policies/{policyId}` | Get a policy | Any authenticated role |
| GET | `/mga/policies` | List policies across programs (filters: `program_id`, `filing_id`, `status`) | Any authenticated role |
| POST | `/mga/policies/{policyId}/bind` | Bind a quote (`QUOTED` → `BOUND`); consumes tranche and aggregate capacity | MGAUnderwriter |
| POST | `/mga/policies/{policyId}/issue` | Issue a bound policy once premium is collected (`BOUND` → `ISSUED`) | MGAUnderwriter |
| POST | `/mga/policies/{policyId}/cancel` | Request cancellation (`BOUND`/`ISSUED` → `PENDING_CANCELLATION`) | MGAUnderwriter |
| POST | `/mga/policies/{policyId}/reinstate` | Reinstate a cancelled policy within thirty days (`CANCELLED` → `pre_cancel_status`); re-consumes capacity | MGAUnderwriter |
| POST | `/mga/policies/{policyId}/final-audit` | Final premium audit (`audit_status` `NOT_AUDITED` → `AUDITED`); posts the premium delta | MGAUnderwriter |
| POST | `/mga/policies/{policyId}/collections` | Record a premium collection into the trust account | MGAFinance |
| POST | `/mga/programs/{programId}/remittances` | Remit the carrier share of unremitted collections (`CARRIER_REMITTANCE` debit) | MGAFinance |
| GET | `/mga/programs/{programId}/trust-ledger` | List trust ledger entries of a program (filter: `entry_type`) | Any authenticated role |
| GET | `/mga/trust-ledger-entries/{entryId}` | Get a trust ledger entry | Any authenticated role |
| GET | `/mga/trust-ledger-entries` | List trust ledger entries across programs (filters: `program_id`, `policy_id`, `claim_id`, `entry_type`) | Any authenticated role |
| POST | `/mga/policies/{policyId}/claims` | Report a claim; assigns a TPA via the appointment selector | MGAUnderwriter |
| GET | `/mga/policies/{policyId}/claims` | List claims of a policy (filter: `status`) | Any authenticated role |
| GET | `/mga/claims/{claimId}` | Get a claim | Any authenticated role |
| GET | `/mga/claims` | List claims across programs (filters: `program_id`, `assigned_tpa_id`, `policy_id`, `status`) | Any authenticated role |
| POST | `/mga/claims/{claimId}/start-review` | TPA starts review (`REPORTED` → `UNDER_REVIEW`) | TPAAdjuster |
| POST | `/mga/claims/{claimId}/set-reserve` | Set the case reserve (`UNDER_REVIEW` self-transition) | TPAAdjuster |
| POST | `/mga/claims/{claimId}/refer` | TPA refers claim to the carrier (`UNDER_REVIEW` → `REFERRED`) | TPAAdjuster |
| POST | `/mga/claims/{claimId}/approve` | Approve claim (`UNDER_REVIEW`/`REFERRED` → `APPROVED`); TPA bounded by authority limit, carrier unbounded | TPAAdjuster, CarrierUnderwriter |
| POST | `/mga/claims/{claimId}/deny` | Deny claim (`UNDER_REVIEW`/`REFERRED` → `DENIED`) | TPAAdjuster, CarrierUnderwriter |
| POST | `/mga/claims/{claimId}/pay` | Pay an approved claim from trust (`APPROVED` → `PAID`) | TPAAdjuster |
| POST | `/mga/claims/{claimId}/reopen` | Reopen a denied claim (`DENIED` → `REOPENED`; at most twice, within ninety days) | MGAUnderwriter |
| POST | `/mga/claims/{claimId}/resume-review` | Resume review of a reopened claim (`REOPENED` → `UNDER_REVIEW`) | TPAAdjuster |
| POST | `/mga/claims/{claimId}/close` | Carrier closes a settled claim (`PAID`/`DENIED` → `CLOSED`) | CarrierUnderwriter |
| POST | `/mga/programs/{programId}/tpa-appointments` | Appoint a TPA for a claim type (`PENDING`) | CarrierUnderwriter |
| GET | `/mga/programs/{programId}/tpa-appointments` | List appointments of a program (filters: `tpa_id`, `status`) | Any authenticated role |
| GET | `/mga/tpa-appointments/{appointmentId}` | Get an appointment | Any authenticated role |
| GET | `/mga/tpa-appointments` | List appointments across programs (filters: `tpa_id`, `program_id`, `status`) | Any authenticated role |
| POST | `/mga/tpa-appointments/{appointmentId}/activate` | Activate appointment (`PENDING` → `ACTIVE`); thirty-day gap check | CarrierUnderwriter |
| POST | `/mga/tpa-appointments/{appointmentId}/suspend` | Suspend appointment; refers its `UNDER_REVIEW` claims | CarrierUnderwriter |
| POST | `/mga/tpa-appointments/{appointmentId}/reinstate` | Reinstate a suspended appointment (`SUSPENDED` → `ACTIVE`) | CarrierUnderwriter |
| POST | `/mga/tpa-appointments/{appointmentId}/revoke` | Revoke appointment (`ACTIVE`/`SUSPENDED` → `REVOKED`) | CarrierUnderwriter |
| POST | `/mga/programs/{programId}/bordereaux` | Draft a bordereau (`DRAFT`); rows may be empty at draft | MGAFinance |
| GET | `/mga/programs/{programId}/bordereaux` | List bordereaux of a program (filters: `bordereau_type`, `status`) | Any authenticated role |
| GET | `/mga/bordereaux/{bordereauId}` | Get a bordereau | Any authenticated role |
| GET | `/mga/bordereaux` | List bordereaux across programs (filters: `program_id`, `bordereau_type`, `status`) | Any authenticated role |
| POST | `/mga/bordereaux/{bordereauId}/submit` | Submit bordereau to the carrier (`DRAFT` → `SUBMITTED`); full data-quality validation | MGAFinance |
| POST | `/mga/bordereaux/{bordereauId}/accept` | Carrier accepts bordereau (`SUBMITTED` → `ACCEPTED`); marks policies/claims as reported | CarrierUnderwriter |
| POST | `/mga/bordereaux/{bordereauId}/reject` | Carrier rejects bordereau (`SUBMITTED` → `REJECTED`) | CarrierUnderwriter |
| POST | `/mga/bordereaux/{bordereauId}/revise` | Return a rejected bordereau to `DRAFT` | MGAFinance |
| POST | `/mga/bordereaux/{bordereauId}/cancel` | Cancel a draft bordereau (`DRAFT` → `CANCELLED`) | MGAFinance |
| POST | `/mga/programs/{programId}/audits` | Schedule a carrier audit (`SCHEDULED`); thirty-day gap check | CarrierAuditor |
| GET | `/mga/programs/{programId}/audits` | List audits of a program (filter: `status`) | Any authenticated role |
| GET | `/mga/audits/{auditId}` | Get an audit | Any authenticated role |
| GET | `/mga/audits` | List audits across programs (filters: `program_id`, `status`) | Any authenticated role |
| POST | `/mga/audits/{auditId}/start` | Start audit (`SCHEDULED` → `IN_PROGRESS`) | CarrierAuditor |
| POST | `/mga/audits/{auditId}/issue-findings` | Issue findings (`IN_PROGRESS` → `FINDINGS_ISSUED`) | CarrierAuditor |
| POST | `/mga/audits/{auditId}/submit-remediation` | MGA submits remediation (`FINDINGS_ISSUED` → `REMEDIATION`); marks listed findings resolved | MGAUnderwriter |
| POST | `/mga/audits/{auditId}/close` | Close audit (`FINDINGS_ISSUED`/`REMEDIATION` → `CLOSED`) if no unresolved `MAJOR`/`CRITICAL` findings | CarrierAuditor |
| POST | `/mga/audits/{auditId}/escalate` | Escalate an audit with an unresolved `CRITICAL` finding; suspends the program with the full cascade | CarrierAuditor |
| POST | `/mga/programs/{programId}/loss-evaluations` | Run a loss-ratio evaluation snapshot; `TERMINATION_REVIEW` auto-suspends the program | CarrierUnderwriter |
| GET | `/mga/programs/{programId}/loss-evaluations` | List loss evaluations of a program | Any authenticated role |
| GET | `/mga/loss-evaluations/{evaluationId}` | Get a loss evaluation | Any authenticated role |
| GET | `/mga/loss-evaluations` | List loss evaluations across programs (filter: `program_id`) | Any authenticated role |
| POST | `/mga/_clock/set_current_utc` | Set the logical clock (startup default 2026-08-01T00:00:00Z; the server never falls back to wall-clock time) | PlatformAdmin |
| POST | `/mga/_ops/run-daily` | Daily ops checkpoint: processes due cancellations, policy expiries, quote lapses, appointment expiries, and bordereau overdue flags | PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below lists every error identifier with its HTTP status. Trigger conditions are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NAIC_CODE_EXISTS` | 409 Conflict |
| `ERR_LICENSE_NUMBER_EXISTS` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROGRAM_TERMINAL` | 409 Conflict |
| `ERR_AUTHORITY_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TRUST_INSUFFICIENT_FUNDS` | 422 Unprocessable Entity |
| `ERR_TRUST_FLOOR_BREACH` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_COVERAGE_PERIOD` | 422 Unprocessable Entity |
| `ERR_REPORTING_DEADLINE_MISSED` | 422 Unprocessable Entity |
| `ERR_POLICY_WINDOW_OUTSIDE_FILING` | 422 Unprocessable Entity |
| `ERR_QUOTE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_FILING_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_FILING_NOT_YET_EFFECTIVE` | 422 Unprocessable Entity |
| `ERR_APPOINTMENT_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_APPOINTMENT_WINDOW_GAP` | 422 Unprocessable Entity |
| `ERR_AUDIT_WINDOW_GAP` | 422 Unprocessable Entity |
| `ERR_AUDIT_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_REOPEN_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_REINSTATE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_STATE_NOT_COVERED` | 422 Unprocessable Entity |
| `ERR_CLASS_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_GUIDELINE_PREMIUM_LIMIT` | 422 Unprocessable Entity |
| `ERR_GUIDELINE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_APPROVED_EXCEEDS_CLAIMED` | 422 Unprocessable Entity |
| `ERR_REOPEN_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_EMPTY_BORDEREAU` | 422 Unprocessable Entity |
| `ERR_BORDEREAU_PERIOD_COVERED` | 422 Unprocessable Entity |
| `ERR_BORDEREAU_DUPLICATE_ROW` | 422 Unprocessable Entity |
| `ERR_NO_CRITICAL_FINDING` | 422 Unprocessable Entity |
| `ERR_NO_EFFECTIVE_FILING` | 422 Unprocessable Entity |
| `ERR_CLASS_NOT_FILED` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_TPA` | 422 Unprocessable Entity |
| `ERR_APPOINTMENT_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_BORDEREAU_ROW_UNKNOWN_POLICY` | 422 Unprocessable Entity |
| `ERR_TPA_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_TRANCHE_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_ALLOCATION` | 422 Unprocessable Entity |
| `ERR_PREMIUM_NOT_COLLECTED` | 422 Unprocessable Entity |
| `ERR_NOTHING_TO_REMIT` | 422 Unprocessable Entity |
| `ERR_REMITTANCE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_BORDEREAU_ROW_MISMATCH` | 422 Unprocessable Entity |
| `ERR_BORDEREAU_TOTAL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TRUST_NOT_ZERO` | 422 Unprocessable Entity |
| `ERR_PROGRAM_HAS_ACTIVE_POLICIES` | 422 Unprocessable Entity |
| `ERR_OPEN_CLAIMS_EXIST` | 422 Unprocessable Entity |
| `ERR_UNACCEPTED_BORDEREAUX` | 422 Unprocessable Entity |
| `ERR_UNRESOLVED_CRITICAL_FINDINGS` | 422 Unprocessable Entity |
| `ERR_INTERNAL` | 500 Internal Server Error |
