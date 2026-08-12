# Anti-Bribery Due Diligence API — Product Requirements Document

## 1. Introduction

Anti-bribery law — the U.S. Foreign Corrupt Practices Act chief among it — holds a company responsible not only for what its own employees do, but for what the intermediaries acting on its behalf do: the consultants, customs brokers, lobbyists, and channel partners who touch government officials in high-risk jurisdictions. A defensible compliance program therefore cannot be a folder of PDFs. It must score every counterparty before onboarding, screen it against sanctions and politically-exposed-person lists, escalate red flags into enhanced review, police the money that flows to the third party afterward, and re-verify the relationship on a schedule — with every decision attributable to a named operator and every dollar traceable to a contract.

This document specifies a REST API, mounted under `/compliance`, that implements that program end to end. The service maintains country risk profiles and a weighted scoring policy; walks each third party from registration through screening, questionnaire, and enhanced due diligence to an approval decision; gates contract activation on tier-appropriate anti-corruption clauses and verified certifications; applies a country-adjusted reasonableness test to every commission payment; runs a pre-approval registry for gifts and hospitality extended to government officials; and drives periodic re-diligence, contractual audit rights, and mandatory compliance training. Six operator roles collaborate under strict segregation of duties, and a deterministic logical clock makes every time-based rule — certification lapse, re-diligence overdue, contract expiry — reproducible in test.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Six roles exist, spelled exactly as follows: `ComplianceAdmin`, `BusinessSponsor`, `ScreeningAnalyst`, `ComplianceOfficer`, `FinanceReviewer`, and `AuditLead`. A `ComplianceAdmin` is the platform compliance administrator and owns risk configuration, the logical clock, and training assignments. A `BusinessSponsor` is the business owner who onboards a third party and submits its questionnaires, contracts, certifications, payment requests, and gift entries. A `ScreeningAnalyst` runs PEP, adverse-media, and sanctions screening dispositions and may raise manual red flags. A `ComplianceOfficer` is the compliance reviewer responsible for questionnaires, red flags, escalations, approvals, suspensions, contract activation, certifications, gifts, and re-diligence. A `FinanceReviewer` reviews commission and payment reasonableness in a maker-checker pairing with sponsors and with peer reviewers. An `AuditLead` exercises contractual audit rights and reports findings.

For every one of these six roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server never compares it against any resource's `id`. It is, however, recorded on resources the operator creates or acts upon — as `sponsor_user_id` on a third party, `submitted_by_user_id` and `approved_by_user_id` on a payment request, `escalated_by_user_id` on red flags and escalation cases, and `assignee_user_id` on training assignments — and ownership and segregation-of-duties checks compare those recorded fields against the caller's `X-User-ID`, never against an entity `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, rendered from wall-clock time at the moment the response is written; as a diagnostic envelope field it is not date-sensitive behavior and does not read the logical clock of §2.5.
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

List endpoints accept two query parameters: `limit`, defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`, defaulting to 0. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in its `meta` object. All list results are ordered by `created_at` ascending, so the oldest record appears first.

### 2.4. Resource Identity, Timestamps, and Nested Retrieval

Every resource in this API — country risk profile, scoring policy, third party, screening check, questionnaire, red flag, escalation case, contract, certification, payment request, gift entry, re-diligence cycle, audit exercise, and training assignment — carries the same four common properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps rendered with three fractional digits, both stamped from the logical compliance clock of §2.5 rather than from wall-clock time, so a record created before any clock set carries the startup instant 2026-05-01T00:00:00Z; `created_at` is fixed at creation and `updated_at` refreshes on every mutation. The `version` field is an integer optimistic-concurrency counter, incremented by one at each mutation point called out in §3.

Routes that address a sub-resource through its parent validate path parameters left to right: each identifier must resolve to an existing record before the next segment is examined, and the first unresolved identifier yields `ERR_NOT_FOUND` (HTTP 404). The path parameters used across the API are `profile_id`, `policy_id`, `third_party_id`, the generic `id` used by several collection routes, `check_id`, `questionnaire_id`, `flag_id`, `case_id`, `contract_id`, `certification_id`, `payment_id`, `entry_id`, `cycle_id`, `audit_id`, and `assignment_id`. A creation payload that references configuration by code rather than by id — the `country_code` supplied when registering a third party — is resolved against the configuration table at the same existence tier, and an unknown code is likewise `ERR_NOT_FOUND`.

### 2.5. The Logical Compliance Clock and the Deterministic Sweep

All date-sensitive behavior in the system reads from a logical clock, never from wall-clock time. At startup, before any operator intervention, the clock reads exactly 2026-05-01T00:00:00Z. A `ComplianceAdmin` may set the clock to any ISO-8601 instant — there is no monotonicity constraint, so the clock may move backward as freely as forward — by supplying `to_iso8601`; the capability answers with the new `current_utc`.

Every clock set runs one deterministic sweep, in which the server: lapses certifications whose validity has passed; marks re-diligence cycles overdue and suspends third parties whose overdue cycles have aged past the grace period; marks training assignments overdue; and expires contracts whose engagement window has closed. All of these comparisons are strictly-greater comparisons on whole ISO dates: a certification lapses only when the current date is later than its `valid_until`, a contract expires only when the current date is later than its `end_date`, a training assignment or re-diligence cycle becomes overdue only when the current date is later than its `due_date`, and the due date itself is not yet overdue.

### 2.6. Money, Percentages, Scores, and Rounding

Monetary amounts are integer cents throughout: contract values, payment amounts, and gift values are all carried as whole-cent integers and never as fractional units. Percentages — the commission ratio and the policy's commission caps — are carried with two decimal places. Risk scores are integers from 0 to 100 produced by rounding half-up. Foreign-exchange conversion for gift entries rounds each entry's USD value half-up to integer cents before any aggregation; the system never sums raw local-currency values and rounds afterward. Calendar arithmetic uses whole ISO dates, with the comparison directions stated alongside each rule in §3.

### 2.7. Optimistic Concurrency Control

Three write operations require the caller to prove it has observed the current state of a parent record, because each of them silently replaces something a stale client would never have seen. Issuing a questionnaire for a third party and updating a third party's profile each require the non-optional field `expected_third_party_version`, carrying the third party's `version` as the client last read it; issuing legitimately supersedes any prior unanswered questionnaire, and a profile update feeds the provisional risk score, so in both cases a stale base would corrupt downstream state. Activating a scoring policy requires the non-optional field `expected_policy_version`, carrying that policy's last-observed `version`; activation supersedes whichever policy is currently active, so a stale activation would swap the global scoring basis the client never reviewed. In all three cases a mismatch with the parent's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field.

### 2.8. Segregation of Duties and Resource Ownership

Maker and checker are always different people. The operator who approves a payment request must differ from the `submitted_by_user_id` recorded on it; the operator who reverses an approved payment must differ from the `approved_by_user_id` recorded on it, so a reviewer can never unwind their own approval; and the officer who decides an escalation case must differ from the case's `escalated_by_user_id` whenever that field is non-null. System-initiated escalations carry a null `escalated_by_user_id` and impose no restriction on the decider. Each violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

Ownership binds a sponsor to their own book of third parties. The `sponsor_user_id` stamped at registration is compared against the caller's `X-User-ID` whenever a sponsor updates a third-party profile, submits a third party for screening, submits questionnaire answers, or submits a certification document; acting on another sponsor's record is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

### 2.9. Validation Priority Order

When a request violates several rules at once, the reported error is determined by a fixed priority order, and a failure at an earlier tier masks every later tier. First, authentication: missing or invalid headers yield `ERR_UNAUTHENTICATED`. Second, role authorization: an unauthorized role yields `ERR_UNAUTHORIZED_ROLE`. Third, existence, evaluated left to right across the path: any unresolved identifier — or an unresolvable `country_code` at third-party registration — yields `ERR_NOT_FOUND`. Fourth, optimistic concurrency: a stale `expected_third_party_version` or `expected_policy_version` yields `ERR_STALE_VERSION`. Fifth, state-machine legality: within this tier the terminal-state check is evaluated first and takes precedence, so an action against an entity already in a terminal state reports `ERR_ALREADY_TERMINAL`, and only otherwise does an illegal from-state report `ERR_INVALID_STATE`. Sixth, sanctions safety: a government-official gift tied to a sanctioned country yields `ERR_COUNTRY_SANCTIONED`. Seventh, temporal rules: `ERR_EVENT_IN_PAST`, `ERR_AUDIT_NOTICE_TOO_SHORT`, and `ERR_AUDIT_WINDOW_OVERLAP`. Eighth, business constraints: `ERR_SOD_VIOLATION`, `ERR_NOT_RESOURCE_OWNER`, `ERR_CLAUSE_SET_INCOMPLETE`, `ERR_DUPLICATE_ACTIVE_CYCLE`, `ERR_FINDINGS_PENDING`, and the malformed-request catch-all `ERR_VALIDATION` (HTTP 400). Ninth, referential business prerequisites: `ERR_POLICY_NOT_ACTIVE`, `ERR_SPONSOR_TRAINING_OVERDUE`, `ERR_SCREENING_UNRESOLVED`, `ERR_QUESTIONNAIRE_NOT_ACCEPTED`, `ERR_RED_FLAGS_OPEN`, `ERR_THIRD_PARTY_NOT_APPROVED`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_CERTIFICATION_REQUIRED`, `ERR_CERTIFICATION_LAPSED`, and `ERR_REDILIGENCE_OVERDUE`. Tenth, fiscal caps: `ERR_ENHANCED_REVIEW_REQUIRED`, `ERR_COMMISSION_CAP_EXCEEDED`, and `ERR_GIFT_CAP_EXCEEDED`.

### 2.10. State Machines and Terminal-State Lockdown

Every lifecycle entity carries a status field with an exact set of uppercase state strings: a third party moves through `onboarding_status`; a screening check through `check_status`; a questionnaire through `questionnaire_status`; a red flag through `flag_status`; an escalation case through `case_status`; a contract through `contract_status`; a certification through `cert_status`; a payment request through `payment_status`; a gift entry through `entry_status`; a re-diligence cycle through `cycle_status`; an audit exercise through `audit_status`; a training assignment through `training_status`; and a scoring policy through `policy_status`. Terminal states — `REJECTED` and `TERMINATED` for a third party; `CLEAR`, `HIT_CONFIRMED`, and `HIT_DISMISSED` for a check; `ACCEPTED` and `SUPERSEDED` for a questionnaire; `CLEARED` and `SUBSTANTIATED` for a red flag; `DECIDED` for a case; `EXPIRED` and `TERMINATED` for a contract; `BLOCKED` and `REVERSED` for a payment; `REJECTED` and `VOIDED` for a gift entry; `COMPLETED` for a cycle; `CLOSED` for an audit; `COMPLETED` for a training assignment; `SUPERSEDED` for a policy — are locked: any further action attempted against an entity in one of them is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409), while a transition the machine does not permit from the entity's current non-terminal state is rejected with `ERR_INVALID_STATE` (HTTP 409). Certifications are the exception that proves the rule: they have no terminal state, because a `REJECTED` certification may be resubmitted and even a `LAPSED` one remains part of the record.

## 3. Business Logic & Workflows

### 3.1. Risk Configuration: Country Profiles and the Scoring Policy

Before any third party can be onboarded, a `ComplianceAdmin` builds the risk basis. Each country risk profile records a `country_code` (an ISO 3166-1 alpha-2 code, unique across profiles — the server refuses duplicates), a `cpi_score` (the Corruption Perceptions Index from 0 to 100, where higher means cleaner), and a `sanctioned` flag that defaults to false. The profile feeds scoring through a derived quantity, `country_norm`, which is 100 minus the `cpi_score`, so that a more corrupt country produces a larger number. Updating a profile's `cpi_score` or `sanctioned` flag is not a silent configuration tweak: the change recomputes both score variants for every non-terminal third party registered under that `country_code`, keeping each third party's questionnaire and screening modifiers intact. Flipping `sanctioned` to true is graver still — every non-terminal third party in that country is forced to a score of 100 and the `CRITICAL` tier, and the system raises a `SYSTEM`-sourced red flag of `CRITICAL` severity on each, which auto-escalates exactly as a confirmed sanctions hit would: the flag moves to `UNDER_ENHANCED_REVIEW`, an escalation case opens in `ENHANCED_DD` with a null `escalated_by_user_id`, and the third party itself drops from `APPROVED` to `SUSPENDED` or, if still mid-onboarding, from `SCREENING` or `DD_REVIEW` to `ENHANCED_REVIEW`.

The scoring policy is the second half of the basis. Its three component weights — `w_country`, `w_industry`, and `w_touchpoint` — must sum to exactly 100, and any other total is a malformed request rejected with `ERR_VALIDATION`. Its three tier thresholds, `tier_medium_min`, `tier_high_min`, and `tier_critical_min`, are inclusive lower bounds: a score at or above `tier_critical_min` maps to `CRITICAL`; otherwise a score at or above `tier_high_min` maps to `HIGH`; otherwise a score at or above `tier_medium_min` maps to `MEDIUM`; anything lower is `LOW`. Two commission caps ride on the same policy: `commission_base_cap_pct`, the base cap as a two-decimal percentage of contract value before any country adjustment, and `commission_hard_cap_pct`, the absolute ceiling a ratio may never exceed. A policy is created in `DRAFT`. Activation — which requires `expected_policy_version` per §2.7 — moves it from `DRAFT` to `ACTIVE`, flips whichever policy was previously `ACTIVE` to `SUPERSEDED`, and increments the policy's `version` by one, so at most one policy is ever `ACTIVE`. Both the submit and the approve paths in the onboarding flow demand that exactly one active policy exist; when none does, they fail with `ERR_POLICY_NOT_ACTIVE` (HTTP 422).

### 3.2. Third-Party Registration, Submission, and Provisional Scoring

A `BusinessSponsor` begins onboarding by registering the counterparty with its `legal_name`, `country_code`, `industry`, and `government_touchpoint`. The `country_code` must resolve to an existing country risk profile, else the create fails with `ERR_NOT_FOUND`. The `industry` is one of `TECHNOLOGY` (industry score 20), `LOGISTICS` (40), `CONSULTING` (60), `CONSTRUCTION` (70), or `GOVERNMENT_RELATIONS` (90), and the `government_touchpoint` is one of `NONE` (touchpoint score 0), `INDIRECT` (50), or `DIRECT` (100) — the parenthesized values are the scores the weighted formula consumes. The server stamps `sponsor_user_id` from the caller's header, sets `onboarding_status` to `DRAFT`, initializes `gov_gift_rolling_12m_cents` to 0, and leaves `risk_score_provisional`, `risk_score_final`, `risk_tier`, `approval_tier_snapshot`, `approved_policy_id`, and `diligence_expires_at` empty until the workflows below produce them. The third-party collection can be listed with the filters `onboarding_status`, `risk_tier`, `country_code`, and `sponsor_user_id`.

While the record remains in `DRAFT`, the owning sponsor may correct `legal_name`, `industry`, or `government_touchpoint` through a profile update carrying `expected_third_party_version`. Once the party has left `DRAFT` the same update is an illegal transition (`ERR_INVALID_STATE`), and a stale version token is caught earlier still by the concurrency tier (`ERR_STALE_VERSION`), because the updated fields feed the provisional score and must never be scored from a base the client has not observed. Each accepted update increments the third party's `version` by one.

Submitting the third party moves `onboarding_status` from `DRAFT` to `SCREENING`. Three gates guard the transition, and under the priority order of §2.9 the ownership check surfaces before the two referential ones: the caller must be the recorded sponsor (`ERR_NOT_RESOURCE_OWNER`); the caller must hold no training assignment in `OVERDUE` status (`ERR_SPONSOR_TRAINING_OVERDUE`); and exactly one scoring policy must be `ACTIVE` (`ERR_POLICY_NOT_ACTIVE`). A successful submit computes `risk_score_provisional` and the first `risk_tier`, auto-creates three screening checks — one `PEP`, one `ADVERSE_MEDIA`, one `SANCTIONS`, created in that order and each `QUEUED`, so the created-at-ascending list of a party's checks reads in the same order — and increments the third party's `version` by one.

The provisional variant of the risk score is a weighted blend of the three components. Multiply `country_norm` by `w_country`, the industry score by `w_industry`, and the touchpoint score by `w_touchpoint`; sum the three products; divide by 100; and round half-up to an integer between 0 and 100. The tier is then read off the active policy's thresholds using the inclusive boundaries of §3.1. One override is evaluated after the arithmetic: if the party's country profile has `sanctioned` set to true, the score is forced to 100 and the tier to `CRITICAL` regardless of the blend.

Thereafter the machine advances itself. After every screening disposition, the server re-checks whether all three of the party's checks have reached a terminal state — `CLEAR`, `HIT_CONFIRMED`, or `HIT_DISMISSED` — and, if the party is still sitting in `SCREENING`, moves it to `DD_REVIEW`. The "still in `SCREENING`" clause matters: a critical escalation triggered by a confirmed sanctions hit may already have pulled the party into `ENHANCED_REVIEW`, and in that case no auto-advance occurs.

### 3.3. Screening Dispositions and the Red-Flag Cascade

A `ScreeningAnalyst` dispositions each check. From `QUEUED`, an `outcome` of `CLEAR` closes the check clean, while `POTENTIAL_HIT` parks it pending adjudication and requires the analyst to supply `match_detail` describing the matched subject — omitting it is a malformed request (`ERR_VALIDATION`). From `POTENTIAL_HIT`, an `outcome` of `HIT_DISMISSED` closes the check as a false positive, and `HIT_CONFIRMED` declares the match real. Dispositions against an already-terminal check are refused with `ERR_ALREADY_TERMINAL`.

Confirming a hit fires a four-level cascade. First, the server recomputes the party's `risk_score_provisional` and `risk_tier` under the confirmed hit: a confirmed `SANCTIONS` check overrides the score to 100 and forces `CRITICAL`, while the `PEP` and `ADVERSE_MEDIA` increments are reserved for the final variant described in §3.4. Second, a red flag is created with `source_type` `SCREENING`, `source_ref_id` pointing at the confirming check, `flag_status` `OPEN`, and a severity keyed to the check's `check_type` — `CRITICAL` for `SANCTIONS`, `HIGH` for `PEP`, `MEDIUM` for `ADVERSE_MEDIA`. Third, but only when that severity is `CRITICAL`, the newborn flag is immediately escalated: it moves from `OPEN` to `UNDER_ENHANCED_REVIEW`, and an escalation case opens in `ENHANCED_DD` with a null `escalated_by_user_id` to mark it as system-initiated. Fourth, again only for `CRITICAL`, the third party itself lurches — from `APPROVED` to `SUSPENDED` if it had already been approved, or from `SCREENING` or `DD_REVIEW` to `ENHANCED_REVIEW` if still onboarding. Only after this cascade does the server re-evaluate the screening-to-review auto-advance of §3.2, and only if the party is still in `SCREENING`.

Red flags also arise by hand. A `ComplianceOfficer` or `ScreeningAnalyst` may raise one on any third party that has moved past `DRAFT`, supplying a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` and a free-text `description`; the flag is born `OPEN` with `source_type` `MANUAL` and a null `source_ref_id`. A manually raised `CRITICAL` flag auto-escalates at creation exactly as a screening-sourced one does — flag to `UNDER_ENHANCED_REVIEW`, case opened in `ENHANCED_DD`, third party suspended or pushed into enhanced review — and the same treatment applies to the `SYSTEM`-sourced flags of §3.1 and the `AUDIT`-sourced flags of §3.9. The `source_type` vocabulary is `SCREENING`, `QUESTIONNAIRE`, `AUDIT`, `SYSTEM`, and `MANUAL`; the `source_ref_id` points at the originating screening check for `SCREENING` flags and at the originating audit exercise for `AUDIT` flags, and is null for the other sources. An officer dispositions an `OPEN` flag with a `disposition` of `CLEARED` or `ESCALATE` plus an optional `note`. Clearing is unavailable for `CRITICAL` flags — they can only be resolved by the escalation decision of §3.5 — and escalating records the acting officer as the case's `escalated_by_user_id` while driving the same third-party status move as the automatic path. Flags under enhanced review are resolved only by that decision, never directly. A party's flags can be listed with the filters `flag_status` and `severity`.

### 3.4. The Due-Diligence Questionnaire and Final Scoring

A `ComplianceOfficer` issues the questionnaire. Issuance is permitted while the third party is in `SCREENING`, `DD_REVIEW`, or `ENHANCED_REVIEW` — against any other status it fails with `ERR_INVALID_STATE` — and it is one of the three version-checked writes of §2.7, so the request must carry `expected_third_party_version` matching the party's current `version` or be rejected with `ERR_STALE_VERSION`. Issuing creates the questionnaire in `ISSUED`, flips any predecessor still sitting in `ISSUED`, `SUBMITTED`, or `RETURNED` to `SUPERSEDED`, and increments the third party's `version` by one; an `ACCEPTED` predecessor is terminal and is left untouched.

The owning sponsor answers from `ISSUED` or `RETURNED`, moving the questionnaire to `SUBMITTED` with three inputs: `government_ownership_pct` (an integer from 0 to 100 — a value outside that range is `ERR_VALIDATION`), `has_facilitation_payments`, and `uses_sub_agents`. Only the current, non-superseded questionnaire may be submitted, and only by the recorded sponsor (`ERR_NOT_RESOURCE_OWNER`). Submission computes `red_flag_count`, the number of risky answers among the three: government ownership above zero, facilitation payments admitted, sub-agents in use. An officer who finds the answers deficient returns the questionnaire — `SUBMITTED` back to `RETURNED` with an optional `return_note` — and the sponsor may resubmit, looping until the officer is satisfied.

Acceptance is the scoring event. The officer may accept only while the third party is in `DD_REVIEW` or `ENHANCED_REVIEW` (otherwise `ERR_INVALID_STATE`), only the current questionnaire (`ERR_INVALID_STATE`), and only once every screening check on the party is terminal — because a questionnaire may legitimately have been issued while screening was still running, acceptance is the point that verifies screening caught up, failing with `ERR_SCREENING_UNRESOLVED` if any check is still `QUEUED` or `POTENTIAL_HIT`. Acceptance moves the questionnaire to `ACCEPTED` and computes `risk_score_final`, then re-derives `risk_tier` from it through the same inclusive thresholds.

The final variant starts from the provisional score and adds two modifiers. The questionnaire modifier is 10 when `government_ownership_pct` is above zero, plus 15 when `has_facilitation_payments` is true, plus 5 when `uses_sub_agents` is true. The screening modifier sums 20 for each confirmed `PEP` hit and 10 for each confirmed `ADVERSE_MEDIA` hit across the party's checks. The sum is clamped to the 0-to-100 band. After the arithmetic, the overrides apply: a sanctioned country profile, or any confirmed `SANCTIONS` check, forces the score to 100 and the tier to `CRITICAL`. For identical base inputs the two variants therefore differ whenever any modifier is non-zero — a provisional 73 can become a final 100.

### 3.5. Escalation, Enhanced Review, and the Third-Party Decision Lifecycle

Escalation cases are never created by hand; they are opened by the escalation mechanics of §3.3 and §3.9 and discovered through the party's case list. A case lives in `ENHANCED_DD` until a `ComplianceOfficer` decides it, moving `case_status` to `DECIDED`. The decision payload carries an `outcome` of `APPROVE_WITH_CONDITIONS`, `REJECT`, or `TERMINATE`, plus an optional `conditions_note` that records the conditions when approving with conditions. Segregation of duties applies at the decision: the deciding officer's identity must differ from the case's `escalated_by_user_id` whenever that field is non-null, else `ERR_SOD_VIOLATION`; auto-escalated cases carry a null escalator and may be decided by any officer. One outcome is status-sensitive — `REJECT` is valid only while the third party sits in `ENHANCED_REVIEW`, because a party suspended after approval must be ended with `TERMINATE` instead.

Each outcome fans out across flags and the party itself. `APPROVE_WITH_CONDITIONS` clears the linked flags to `CLEARED` and restores the third party — from `ENHANCED_REVIEW` back to `DD_REVIEW`, or from `SUSPENDED` back to `APPROVED`. `REJECT` substantiates the linked flags and moves the party to `REJECTED`. `TERMINATE` substantiates the linked flags and moves the party to `TERMINATED` with the full termination cascade described below. The chosen outcome is recorded as the case's `decision_outcome`.

Beyond escalation decisions, the officer holds the party's direct lifecycle verbs. Approval — permitted only from `DD_REVIEW` — first requires a referential triple, evaluated under §2.9's priority order with the active-policy check listed first: exactly one scoring policy must be `ACTIVE` (`ERR_POLICY_NOT_ACTIVE`); the current questionnaire must be `ACCEPTED`, which is precisely the condition that `risk_score_final` is non-null (`ERR_QUESTIONNAIRE_NOT_ACCEPTED`); and the party must hold no `OPEN` or `UNDER_ENHANCED_REVIEW` red flag and no `ENHANCED_DD` escalation case — a single error, `ERR_RED_FLAGS_OPEN`, covers both, because an open case always implies an escalated flag. Approval stamps `approval_tier_snapshot` with the current `risk_tier` and `approved_policy_id` with the active policy's id — from then on, contract clause requirements key off this snapshot rather than the live tier — sets `diligence_expires_at` to the current date plus the tier's re-diligence interval (365 days for `LOW` or `MEDIUM`, 180 days for `HIGH`, 90 days for `CRITICAL`), auto-creates the first re-diligence cycle with `trigger_source` `SCHEDULED`, status `SCHEDULED`, and `due_date` equal to `diligence_expires_at`, and increments the party's `version` by one.

Rejection from `SCREENING` or `DD_REVIEW` moves the party to the terminal `REJECTED` state and accepts an optional `reason`. Suspension moves an `APPROVED` party to `SUSPENDED` — by officer action with an optional `reason`, by the system when a `CRITICAL` flag auto-escalates, or by the clock sweep when a re-diligence cycle has been `OVERDUE` for more than 30 days. Reinstatement returns a `SUSPENDED` party to `APPROVED` once no `OPEN` or `UNDER_ENHANCED_REVIEW` flag and no `ENHANCED_DD` case remains (`ERR_RED_FLAGS_OPEN` otherwise), and is equally reachable through an escalation decision of `APPROVE_WITH_CONDITIONS`. Rejection, suspension, and reinstatement each increment the party's `version` by one.

Termination, from `APPROVED` or `SUSPENDED` — whether by officer action with an optional `reason`, by an escalation decision of `TERMINATE`, or by a re-diligence completion of `TERMINATE` — fires the full cascade: every contract of the party in `DRAFT`, `PENDING_CLAUSES`, or `ACTIVE` moves to `TERMINATED`; every payment request still `SUBMITTED` on those contracts moves to `BLOCKED`; every gift entry still `PENDING_APPROVAL` moves to `REJECTED`; and the party's `version` increments by one. Together with the `APPROVED`-to-`SUSPENDED`-and-back loop and the `DD_REVIEW`-to-`ENHANCED_REVIEW`-and-back loop, these give the party lifecycle its deliberately cyclic shape.

### 3.6. Contracts, Clause Sets, and Certifications

Once a third party is `APPROVED`, the owning sponsor may draft a contract against it by supplying `contract_value_cents` (a strictly positive integer of USD cents — the denominator of every commission ratio), a `start_date`, and an `end_date` that must be later than the start date (`ERR_VALIDATION` otherwise). Creating against a party in any other status fails with `ERR_THIRD_PARTY_NOT_APPROVED`. The contract is born in `DRAFT` with its payment ledger, `approved_payments_total_cents`, at zero.

Attaching clause codes moves the contract from `DRAFT` to `PENDING_CLAUSES` and stores the supplied `clause_codes`; the party must still be `APPROVED` (`ERR_THIRD_PARTY_NOT_APPROVED`). Activation by a `ComplianceOfficer` then enforces the tier-appropriate paperwork. The attached `clause_codes` must cover the required set derived from the party's `approval_tier_snapshot`: `ABAC` alone for `LOW` or `MEDIUM`; `ABAC`, `AUDIT_RIGHTS`, and `ANNUAL_CERTIFICATION` for `HIGH`; and for `CRITICAL` those three plus `TERMINATION_FOR_CAUSE` and `GOVT_OFFICIAL_DISCLOSURE` — a shortfall is `ERR_CLAUSE_SET_INCOMPLETE`. Under the priority order this clause check (a business constraint) is evaluated before the referential gates, so an incomplete clause set surfaces even when the party has meanwhile lost its standing. The referential gates themselves require the party to be `APPROVED` (`ERR_THIRD_PARTY_NOT_APPROVED`), at least one certification in `VERIFIED` status to exist for the party (`ERR_CERTIFICATION_REQUIRED`), and no re-diligence cycle of the party to be `OVERDUE` (`ERR_REDILIGENCE_OVERDUE`). Thereafter the clock sweep flips a `PENDING_CLAUSES` or `ACTIVE` contract to `EXPIRED` once the current date passes its `end_date`. A party's contracts can be listed with the `contract_status` filter, and each contract's detail exposes the live ledger.

Certifications track the party's attestations. An officer issues a requirement by choosing a `cert_type` — `ANNUAL_ABAC` or `CODE_OF_CONDUCT` — against any party not in `REJECTED` or `TERMINATED` (`ERR_INVALID_STATE` against those, with terminal lockdown applying as usual); the certification starts `PENDING`. The owning sponsor submits the `document_ref`, moving `PENDING` — or a previously `REJECTED` certification — to `SUBMITTED`. An officer then verifies it, moving to `VERIFIED` and setting `valid_until` to the verification date plus 365 days, or rejects it with an optional `reason`, moving to `REJECTED` from where resubmission is allowed. The `valid_until` field stays empty until verification, and the clock sweep moves a `VERIFIED` certification to `LAPSED` once the current date passes `valid_until`. A party's certifications can be listed with the `cert_status` filter.

### 3.7. Commissions and Payment Reasonableness

The owning sponsor charges a payment against a contract by supplying a `payment_type` of `COMMISSION`, `SUCCESS_FEE`, or `REIMBURSEMENT`, a strictly positive `amount_cents`, and optionally `enhanced_review_evidence` (defaulting to false), which attests that an approved escalation or evidence package is attached. Creation requires the contract to be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`), stamps `submitted_by_user_id` from the caller, sets `payment_status` to `SUBMITTED`, and computes `ratio_pct` at creation: multiply the amount in cents by 10000, divide by the contract's `contract_value_cents`, round half-up to the nearest integer, then divide by 100 — yielding the payment's two-decimal percentage of contract value.

Reasonableness is judged at approval time by the country-blended cap, with a pinned evaluation order: the ratio being tested is computed first; then `country_norm` for the party's country; then a multiplier of 0.60 when `country_norm` is 70 or higher, 0.80 when `country_norm` is between 40 and 69 inclusive, and 1.00 when `country_norm` is below 40; then the `effective_cap_pct`, which is the policy's `commission_base_cap_pct` multiplied by that multiplier and carried as an exact two-decimal value. The bracket verdict follows: a `ratio_pct` strictly greater than `commission_hard_cap_pct` can never be approved, and any attempt fails with `ERR_COMMISSION_CAP_EXCEEDED`; a `ratio_pct` greater than `effective_cap_pct` but not greater than the hard cap is approvable only with evidence, so approval without `enhanced_review_evidence` set to true fails with `ERR_ENHANCED_REVIEW_REQUIRED`; and a `ratio_pct` at or below `effective_cap_pct` — the boundary is inclusive — is approvable outright. Payments of type `REIMBURSEMENT` skip the brackets entirely and are always approvable on the merits of the other gates. Applying the base cap flat, without the country multiplier, is a known misreading and is non-conformant: the blended cap is the production rule.

A `FinanceReviewer` approves a `SUBMITTED` payment. The checks, in §2.9's priority order: segregation of duties against the recorded `submitted_by_user_id` (`ERR_SOD_VIOLATION`); the contract still `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`); the third party still `APPROVED` (`ERR_THIRD_PARTY_NOT_APPROVED`); at least one certification `VERIFIED` and not lapsed at approval time (`ERR_CERTIFICATION_LAPSED`); and finally the bracket verdict above. Approval stamps `approved_by_user_id` from the reviewer and adds the `amount_cents` into the contract's `approved_payments_total_cents` ledger. Blocking, with an optional `reason`, moves a `SUBMITTED` payment to the terminal `BLOCKED` state — as does the termination cascade of §3.5. Reversal moves an `APPROVED` payment to `REVERSED`, requires the reverser to differ from the recorded `approved_by_user_id` (`ERR_SOD_VIOLATION`) so no reviewer unwinds their own approval, and subtracts the `amount_cents` back out of the ledger. The ledger is a compensating invariant: it always equals the sum of approved amounts minus the sum of reversed amounts, and it never goes negative. A contract's payments can be listed with the `payment_status` filter.

### 3.8. The Gift and Hospitality Registry

Any gift, meal, or trip extended to the third party's side is pre-approved through the registry. The owning sponsor registers an entry with an `entry_type` of `GIFT`, `HOSPITALITY`, or `TRAVEL`; a `recipient_is_government_official` flag; a strictly positive `value_cents` in local-currency cents; a strictly positive `fx_rate_to_usd` decimal rate; and the `event_date`. Registration is permitted while the party is in `DD_REVIEW`, `ENHANCED_REVIEW`, `APPROVED`, or `SUSPENDED` — against any other status it is `ERR_INVALID_STATE`. Each entry's `value_usd_cents` is computed individually at creation as the local value multiplied by the FX rate, rounded half-up to whole cents; aggregations always sum these per-entry rounded figures, never a sum-then-round of raw values. The entry is born `PENDING_APPROVAL`.

Three refusal rules guard creation, surfacing in §2.9's order. Sanctions first: an entry with `recipient_is_government_official` set to true on a party whose country profile is `sanctioned` is refused with `ERR_COUNTRY_SANCTIONED`. Temporal second: pre-approval requires the `event_date` to fall on or after the current date, and a past date is `ERR_EVENT_IN_PAST`. The fiscal cap last: the prospective government-official rolling total — defined below — strictly above 50000 cents rejects the create with `ERR_GIFT_CAP_EXCEEDED`, while a prospective total of exactly 50000 is allowed.

The rolling window belongs to each entry: it opens 365 days before the entry's `event_date` (exclusive) and closes on the `event_date` itself (inclusive). The rolling total sums `value_usd_cents` over the same party's entries that have `recipient_is_government_official` true, `entry_status` `APPROVED`, and an `event_date` inside the window; the prospective total adds the candidate entry's own `value_usd_cents`. Two thresholds hang off the prospective total with deliberately different operators: at or above 25000 cents — inclusive — the entry's computed `requires_enhanced_approval` becomes true, while strictly above 50000 cents is the hard cap. Entries for non-government recipients are excluded from the aggregate and from both caps.

Approval by a `ComplianceOfficer` re-tests both conditions against the world as it now stands: if `requires_enhanced_approval` is true, the approval payload's `enhanced_review_evidence` must be true (`ERR_ENHANCED_REVIEW_REQUIRED`); and the rolling hard cap is re-checked at approval time, so a window total of approved government-official entries plus this entry's `value_usd_cents` strictly above 50000 fails with `ERR_GIFT_CAP_EXCEEDED`. Approval moves the entry to `APPROVED` and recomputes the party's `gov_gift_rolling_12m_cents` — the rolling 365-day sum over the party's approved government-official entries — now including this entry. Rejection with an optional `reason` moves a pending entry to the terminal `REJECTED` state, as does the termination cascade. Voiding with an optional `reason` moves an `APPROVED` entry to `VOIDED` and recomputes the aggregate excluding exactly this entry — the registry's compensating invariant. The aggregate is also recomputed whenever an entry is created, so the party detail always reflects the current window. A party's entries can be listed with the `entry_status` filter.

### 3.9. Re-Diligence, Audit Rights, and Training Compliance

Approval is never permanent. The scheduled cycle created at approval (§3.5) sits in `SCHEDULED` until an officer starts work, moving it to `IN_PROGRESS`, and completes it with an `outcome`. An officer may also open a manual cycle — `trigger_source` `MANUAL`, `due_date` set to the current date plus 30 days — but only when no other cycle of the party is `SCHEDULED`, `IN_PROGRESS`, or `OVERDUE`; otherwise the create fails with `ERR_DUPLICATE_ACTIVE_CYCLE`. The clock sweep moves a `SCHEDULED` or `IN_PROGRESS` cycle to `OVERDUE` once the current date passes its `due_date`, and while any cycle is `OVERDUE` two consequences follow: contract activation for the party is refused (`ERR_REDILIGENCE_OVERDUE`), and once the current date is more than 30 days past the `due_date` the sweep suspends the party automatically — `APPROVED` to `SUSPENDED`.

Completion outcomes fork three ways. `REAFFIRM` extends `diligence_expires_at` to the current date plus the interval of the party's current tier and auto-creates the successor cycle in `SCHEDULED` at that date. `DOWNGRADE` escalates the party's `risk_tier` one step — `LOW` to `MEDIUM`, `MEDIUM` to `HIGH`, `HIGH` to `CRITICAL`, with `CRITICAL` staying put — resets `diligence_expires_at` to the current date plus the interval of the new tier, and schedules the successor cycle just 30 days out. `TERMINATE` ends the party with the full termination cascade of §3.5. The tier intervals are 90 days for `CRITICAL`, 180 for `HIGH`, and 365 for both `MEDIUM` and `LOW`. A party's cycles can be listed with the `cycle_status` filter.

Audit rights turn the `AUDIT_RIGHTS` clause into practice. An `AuditLead` notices an exercise against an `APPROVED` party by supplying `fieldwork_start_date` and `fieldwork_end_date`; the server stamps `notice_date` with the current date and opens the exercise in `NOTICED`. The start date must be at least ten calendar days after the notice date — the boundary is inclusive, so exactly ten days later is legal — or the create fails with `ERR_AUDIT_NOTICE_TOO_SHORT`; the end date must be strictly later than the start date or the payload is `ERR_VALIDATION`. Fieldwork windows are half-open, including their start date and excluding their end date, and a new window conflicts with an existing `NOTICED` or `IN_FIELDWORK` window for the same party when the proposed start falls before the existing window's end and the existing window's start falls before the proposed end — windows that merely touch, where the proposed start equals an existing end, do not conflict. A conflicting create fails with `ERR_AUDIT_WINDOW_OVERLAP`. Beginning fieldwork moves the exercise to `IN_FIELDWORK` and is gated on the same ten-day notice measured against the logical clock: the current date must be at least `notice_date` plus ten days, inclusive, else `ERR_AUDIT_NOTICE_TOO_SHORT`.

Issuing findings takes `findings_total` — zero or more — and `findings_substantiated_critical`, which must lie between zero and `findings_total` inclusive (`ERR_VALIDATION` otherwise), and moves the exercise to `FINDINGS_ISSUED`. When `findings_substantiated_critical` is at least one, the familiar cascade fires: a `CRITICAL` red flag is created with `source_type` `AUDIT` and `source_ref_id` pointing at the exercise, the flag auto-escalates to `UNDER_ENHANCED_REVIEW` with an `ENHANCED_DD` case whose `escalated_by_user_id` is null, and the party drops from `APPROVED` to `SUSPENDED` or from `SCREENING` or `DD_REVIEW` to `ENHANCED_REVIEW`. Closing the exercise requires every red flag spawned by it to have reached `CLEARED` or `SUBSTANTIATED`; while any remains `OPEN` or `UNDER_ENHANCED_REVIEW`, the close fails with `ERR_FINDINGS_PENDING`. A party's exercises can be listed with the `audit_status` filter.

Training closes the loop on the people side. A `ComplianceAdmin` assigns a course by naming the `assignee_user_id`, a `course_code` such as ABAC-101, and a `due_date`; the assignment is born `ASSIGNED`. The clock sweep moves it to `OVERDUE` once the current date passes the `due_date`, and §3.2's submit gate makes an overdue assignment bite: the assignee cannot submit third parties while any of their assignments is `OVERDUE`. Completion moves `ASSIGNED` or `OVERDUE` to `COMPLETED` — late completion is allowed — and is self-service for the assignee, whose `assignee_user_id` must equal their own caller identity, or available to any `ComplianceAdmin`. The assignment list supports the filters `assignee_user_id` and `training_status`.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201; every modification, state-transition action, and read returns HTTP 200. Request and response payloads, preconditions, and side effects are defined by the narratives of §2 and §3; the table below fixes only the HTTP contract and the authorized roles.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /compliance/_clock/set_current_utc | Set the logical clock to any ISO-8601 instant and run the deterministic sweep | ComplianceAdmin |
| POST | /compliance/country-risk-profiles | Create a country risk profile | ComplianceAdmin |
| PATCH | /compliance/country-risk-profiles/{profile_id} | Update CPI and/or the sanctions flag; sanctions-on re-scores the country's non-terminal third parties and escalates | ComplianceAdmin |
| POST | /compliance/risk-scoring-policies | Create a scoring policy in DRAFT | ComplianceAdmin |
| POST | /compliance/risk-scoring-policies/{policy_id}/activate | Activate a DRAFT policy (OCC); the previously ACTIVE policy becomes SUPERSEDED | ComplianceAdmin |
| GET | /compliance/risk-scoring-policies/{policy_id} | Get a scoring policy | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |
| POST | /compliance/third-parties | Register a third party in DRAFT; the caller becomes its sponsor | BusinessSponsor |
| GET | /compliance/third-parties/{third_party_id} | Get third-party detail including computed scores, tier, and rolling gift total | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |
| GET | /compliance/third-parties | List third parties with filters and pagination | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |
| PATCH | /compliance/third-parties/{third_party_id} | Update profile fields while DRAFT (OCC); owning sponsor only | BusinessSponsor |
| POST | /compliance/third-parties/{third_party_id}/submit | Submit for screening: compute the provisional score/tier and auto-create the three checks | BusinessSponsor |
| POST | /compliance/third-parties/{third_party_id}/approve | Approve after due-diligence review; pin the tier/policy snapshot and schedule re-diligence | ComplianceOfficer |
| POST | /compliance/third-parties/{third_party_id}/reject | Reject during screening or due-diligence review (terminal) | ComplianceOfficer |
| POST | /compliance/third-parties/{third_party_id}/suspend | Suspend an approved third party | ComplianceOfficer |
| POST | /compliance/third-parties/{third_party_id}/reinstate | Reinstate a suspended third party with no open flags or cases | ComplianceOfficer |
| POST | /compliance/third-parties/{third_party_id}/terminate | Terminate (terminal) with the full termination cascade | ComplianceOfficer |
| POST | /compliance/screening-checks/{check_id}/disposition | Disposition a screening check; confirming a hit spawns the red-flag cascade | ScreeningAnalyst |
| GET | /compliance/third-parties/{id}/screening-checks | List a third party's screening checks | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |
| POST | /compliance/third-parties/{id}/questionnaires | Issue a questionnaire (OCC on the third party); supersedes unanswered predecessors | ComplianceOfficer |
| POST | /compliance/questionnaires/{questionnaire_id}/submit | Sponsor submits answers; computes the red-flag count | BusinessSponsor |
| POST | /compliance/questionnaires/{questionnaire_id}/accept | Accept a submitted questionnaire; computes the final score and re-derives the tier | ComplianceOfficer |
| POST | /compliance/questionnaires/{questionnaire_id}/return | Return a submitted questionnaire for corrections | ComplianceOfficer |
| GET | /compliance/third-parties/{id}/questionnaires | List a third party's questionnaires | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |
| POST | /compliance/third-parties/{id}/red-flags | Raise a manual red flag; CRITICAL severity auto-escalates | ComplianceOfficer, ScreeningAnalyst |
| POST | /compliance/red-flags/{flag_id}/disposition | Clear or escalate an OPEN flag; CRITICAL flags cannot be cleared directly | ComplianceOfficer |
| GET | /compliance/third-parties/{id}/red-flags | List a third party's red flags | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |
| POST | /compliance/escalation-cases/{case_id}/decide | Decide an ENHANCED_DD case; outcomes drive flags and third-party status | ComplianceOfficer |
| GET | /compliance/third-parties/{id}/escalation-cases | List a third party's escalation cases | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |
| POST | /compliance/third-parties/{id}/contracts | Create a contract in DRAFT; requires the third party APPROVED | BusinessSponsor |
| POST | /compliance/contracts/{contract_id}/attach-clauses | Attach clause codes, moving DRAFT to PENDING_CLAUSES | BusinessSponsor |
| POST | /compliance/contracts/{contract_id}/activate | Activate after validating clause set, certification, and re-diligence currency | ComplianceOfficer |
| GET | /compliance/contracts/{contract_id} | Get contract detail including the approved-payments ledger | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |
| GET | /compliance/third-parties/{id}/contracts | List a third party's contracts | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |
| POST | /compliance/third-parties/{id}/certifications | Issue a certification requirement in PENDING | ComplianceOfficer |
| POST | /compliance/certifications/{certification_id}/submit | Sponsor submits the certification document | BusinessSponsor |
| POST | /compliance/certifications/{certification_id}/verify | Verify a submitted certification; sets validity to one year | ComplianceOfficer |
| POST | /compliance/certifications/{certification_id}/reject | Reject a submitted certification; resubmission allowed | ComplianceOfficer |
| GET | /compliance/third-parties/{id}/certifications | List a third party's certifications | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |
| POST | /compliance/contracts/{id}/payment-requests | Submit a payment request against an ACTIVE contract; computes the ratio at creation | BusinessSponsor |
| POST | /compliance/payment-requests/{payment_id}/approve | Approve: segregation of duties, contract/party/certification gates, and the commission brackets | FinanceReviewer |
| POST | /compliance/payment-requests/{payment_id}/block | Block a submitted payment (terminal) | FinanceReviewer |
| POST | /compliance/payment-requests/{payment_id}/reverse | Reverse an approved payment and compensate the contract ledger | FinanceReviewer |
| GET | /compliance/contracts/{id}/payment-requests | List a contract's payment requests | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |
| POST | /compliance/third-parties/{id}/gift-hospitality-entries | Register a gift/hospitality pre-approval entry with per-entry FX rounding and window checks | BusinessSponsor |
| POST | /compliance/gift-hospitality-entries/{entry_id}/approve | Approve an entry; enhanced entries need evidence; re-checks the rolling hard cap | ComplianceOfficer |
| POST | /compliance/gift-hospitality-entries/{entry_id}/reject | Reject a pending entry (terminal) | ComplianceOfficer |
| POST | /compliance/gift-hospitality-entries/{entry_id}/void | Void an approved entry and repair the rolling aggregate | ComplianceOfficer |
| GET | /compliance/third-parties/{id}/gift-hospitality-entries | List a third party's gift/hospitality entries | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |
| POST | /compliance/third-parties/{id}/rediligence-cycles | Manually trigger a re-diligence cycle due in 30 days; refused while another is active | ComplianceOfficer |
| POST | /compliance/rediligence-cycles/{cycle_id}/start | Start work on a scheduled cycle | ComplianceOfficer |
| POST | /compliance/rediligence-cycles/{cycle_id}/complete | Complete with REAFFIRM, DOWNGRADE, or TERMINATE outcome effects | ComplianceOfficer |
| GET | /compliance/third-parties/{id}/rediligence-cycles | List a third party's re-diligence cycles | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |
| POST | /compliance/third-parties/{id}/audit-exercises | Notice an audit-rights exercise; validates the notice window and window overlap | AuditLead |
| POST | /compliance/audit-exercises/{audit_id}/begin-fieldwork | Begin fieldwork once the ten-day notice has elapsed | AuditLead |
| POST | /compliance/audit-exercises/{audit_id}/issue-findings | Issue findings; a substantiated critical finding fires the escalation cascade | AuditLead |
| POST | /compliance/audit-exercises/{audit_id}/close | Close once every spawned red flag is resolved | AuditLead |
| GET | /compliance/third-parties/{id}/audit-exercises | List a third party's audit exercises | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |
| POST | /compliance/training-assignments | Assign a compliance training to an operator | ComplianceAdmin |
| POST | /compliance/training-assignments/{assignment_id}/complete | Complete an assignment; self-service for the assignee or admin | BusinessSponsor, ComplianceAdmin |
| GET | /compliance/training-assignments | List training assignments with filters and pagination | ComplianceAdmin, BusinessSponsor, ScreeningAnalyst, ComplianceOfficer, FinanceReviewer, AuditLead |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue fixes only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_SOD_VIOLATION | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_POLICY_NOT_ACTIVE | 422 |
| ERR_SPONSOR_TRAINING_OVERDUE | 422 |
| ERR_COUNTRY_SANCTIONED | 422 |
| ERR_EVENT_IN_PAST | 422 |
| ERR_SCREENING_UNRESOLVED | 422 |
| ERR_QUESTIONNAIRE_NOT_ACCEPTED | 422 |
| ERR_RED_FLAGS_OPEN | 422 |
| ERR_CLAUSE_SET_INCOMPLETE | 422 |
| ERR_CERTIFICATION_REQUIRED | 422 |
| ERR_CERTIFICATION_LAPSED | 422 |
| ERR_THIRD_PARTY_NOT_APPROVED | 422 |
| ERR_CONTRACT_NOT_ACTIVE | 422 |
| ERR_COMMISSION_CAP_EXCEEDED | 422 |
| ERR_ENHANCED_REVIEW_REQUIRED | 422 |
| ERR_GIFT_CAP_EXCEEDED | 422 |
| ERR_AUDIT_NOTICE_TOO_SHORT | 422 |
| ERR_AUDIT_WINDOW_OVERLAP | 422 |
| ERR_REDILIGENCE_OVERDUE | 422 |
| ERR_DUPLICATE_ACTIVE_CYCLE | 422 |
| ERR_FINDINGS_PENDING | 422 |
