# Medical Group Governance API — Product Requirements Document

## 1. Introduction

Independent physician groups run their own corporate governance: physicians buy into the practice along a defined partner track, sit on a board with fixed seats and terms, charter standing committees (quality, finance, compensation), vote on motions that carry real money — capital calls, profit distributions, partner buy-outs, even merger offers — and disclose conflicts of interest that can recuse them from those votes. Today these groups run on email threads, spreadsheets, and the managing partner's memory. Quorum is miscounted, a buy-in price is negotiated rather than computed, a distribution exceeds what the operating agreement permits, and a departing shareholder's buy-out valuation is disputed with no auditable trail.

This document specifies the Medical Group Governance API, a system of record for the board and governance lifecycle of an independent physician group. It models the singleton governance policy (quorum, supermajority, buy-in pricing constants, fiscal calendar), the physician roster with its two independent dimensions of partnership tier and disciplinary standing, board seats with booked successors, standing committees whose health is derived from membership against a charter quorum, buy-in offers with priced installment schedules, motions with snapshot-based voting and type-specific adoption effects, capital calls with per-shareholder assessments and a delinquency-to-default sweep, distributions with pro-rata or seniority-tiered allocations, partner exit valuations with appraisal, dispute, and arbitration, conflict-of-interest disclosures whose review can recuse voters and void ballots, and merger proposals that must be ratified by an adopted motion.

A logical clock governs every time read in the system. The server starts at exactly `2026-08-01T00:00:00Z` and never consults the wall clock; administrators advance time explicitly, and each advance runs all time-based sweeps atomically with the clock-set. All monetary amounts are integer cents, and all timestamps are ISO 8601 UTC with millisecond precision.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. The declared role names, spelled exactly, are `BoardAdmin`, `Physician`, and `ComplianceOfficer`.

When `X-User-Role` is `Physician`, `X-User-ID` is the `id` of the acting `Physician`; ownership checks on any resource that references a `Physician` compare the resource's foreign-key field to `X-User-ID`. A physician caller may act only on their own offers, their own votes, their own disclosures, their own exit valuation, and their own assessments; acting on a resource owned by another physician is rejected with `ERR_RESOURCE_OWNERSHIP` (HTTP 403).

When `X-User-Role` is `BoardAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`. The same is true when `X-User-Role` is `ComplianceOfficer`: `X-User-ID` is an opaque operator identifier, recorded for example as `reviewed_by` on a `COIDisclosure` at review time, but never compared to any entity's `id`.

A missing or unrecognized `X-User-Role`, or a missing `X-User-ID` where the role requires one, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-authenticated caller whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). Segregation of duties is structural: only a `ComplianceOfficer` may review a conflict-of-interest disclosure, so the filer of a disclosure is never its reviewer, and a `BoardAdmin` who can do almost everything else still cannot review disclosures.

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

All list endpoints accept two query parameters: `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` defaults to 0. List results are always ordered by `created_at` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties, Money, and Time

Every entity carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp refreshed on every mutation, and a `version` integer that starts at 1 on creation and increments by exactly 1 on every mutation of that entity. Timestamps are ISO 8601 UTC with three fractional digits. All monetary amounts throughout the API are integer cents; percentages are carried as decimal fractions (for example, a ten percent late fee is stored as `0.10`).

All time reads in the system — offer deadlines, voting windows, assessment due dates, board term ends, tenure computations — come from a single logical clock. At server startup the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. An admin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant. Setting the clock runs every time-based sweep atomically with the clock-set: offers past their acceptance deadline transition to `EXPIRED`; motions in `OPEN` or `TABLED` whose closing instant has passed transition to `EXPIRED`; unpaid assessments past their due date transition to `DELINQUENT` with the late fee applied exactly once, and assessments still unpaid past the grace period transition to `DEFAULTED` with the physician suspension cascade; board seats whose current term has ended promote a booked successor or become `VACANT`.

### 2.5. Rounding, Precision, and Residual Pennies

All calculations produce integer cents. Where a rule calls for rounding, it is round-half-up. Some quantities are deliberately floored rather than rounded: per-physician allocation and assessment amounts are floored, and the residual pennies that result are distributed one cent at a time to the largest holders, never by rounding each allocation. Because every timestamp is read from the pinned logical clock, physicians created without an intervening clock advance share an identical `created_at`; whenever a residual-penny ordering among physicians ties completely on its ordering keys — for the share-weighted orderings, equal share counts and an identical `created_at` — recipients are taken in the order the physician records were created, earliest-created first. Ownership percentages are carried at 6 decimal places, round-half-up. Two rounding policies recur often enough to name here: the buy-in price rounds half-up to whole cents at its proration step only, and the distribution cap rounds half-up at each of its two steps.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency. Updating the governance policy requires the request to carry `expected_policy_version`, holding the `version` of the `GovernancePolicy` the client last observed; if the policy's current `version` no longer matches — because another writer has modified it since the client's last read — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from silently discarding an update it never saw. Recording an appraisal against an exit valuation likewise requires `expected_valuation_version` matching the `ExitValuation`'s current `version`; a mismatch — for instance because another writer has already recorded a corrected appraisal that legitimately supersedes the prior value — is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field.

### 2.7. Validation Order

Every request is validated in a fixed priority order, and the first failure wins. First, authentication: the role header must be present and recognized, and the user id must be present for the entity-backed physician role (`ERR_UNAUTHENTICATED`). Second, request shape: required fields present, enum values valid, amounts positive integers, and the payload sub-fields required by the motion type present (`ERR_INVALID_REQUEST`). Third, role permission on the endpoint (`ERR_FORBIDDEN`). Fourth, ownership: a physician caller acting on another physician's resource (`ERR_RESOURCE_OWNERSHIP`). Fifth, existence: path identifiers are validated left to right, and foreign keys referenced in the body must resolve (`ERR_NOT_FOUND`). Sixth, state gates: the target resource must be in a status that permits the operation — the various state errors described in §3. Seventh, compliance gates on voting and sponsorship: recusal, unreviewed disclosures, and segregation of duties. Eighth, temporal gates: voting windows and term windows. Ninth, uniqueness, overlap, and cardinality rules. Tenth and last, money guards: overpayment, the distribution cap, treasury sufficiency, and installment exactness. Because money guards run last, a request that is both malformed in shape and over budget fails with the shape error; a payment that is both a duplicate-vote situation and an overpayment fails with the uniqueness error.

### 2.8. The Governance Policy Singleton

Exactly one `GovernancePolicy` may exist. Its `singleton_key` is always `GLOBAL`, and attempting to create a second policy is rejected with `ERR_POLICY_ALREADY_EXISTS` (HTTP 409). The policy is created with `version` 1 and holds every governance constant: `total_shares_authorized`, `board_quorum_count` (default 5), `supermajority_num` (default 2) and `supermajority_den` (default 3), `voting_window_days` (default 14), `offer_window_days` (default 30), `buy_in_base_shareholder_cents` (default 25000000), `buy_in_base_partner_cents` (default 10000000), `tenure_discount_pct_per_year` (default 0.02), `max_tenure_discount_pct` (default 0.20), `min_buy_in_cents` (default 5000000), `fiscal_year_start_month` (default 7, meaning the fiscal year starts July 1), `late_fee_pct` (default 0.10), `delinquency_grace_days` (default 30), `minority_discount_pct` (default 0.15), `ebitda_multiple` (default 6), `trailing_ebitda_cents` (default 0), `bonus_pool_pct` (default 0.25), `distribution_cap_pct` (default 0.60), `seniority_carve_pct` (default 0.20), `seniority_tier_years` (default 5), `max_dispute_rounds` (default 2), and `max_committee_members` (default 7). Two fields are maintained by the system: `comp_policy_version`, which starts at 0 and increments each time a `COMP_POLICY` motion is adopted, and `treasury_shares`, which is computed as `total_shares_authorized` minus the sum of `shares_held` over all non-`EXITED` physicians.

## 3. Business Logic & Workflows

### 3.1. Physician Roster, Standing, and Ownership

A `BoardAdmin` onboards a physician with `full_name`, `hire_date`, and optionally `specialty`, `founding_shareholder`, and `initial_shares`. A physician created with `founding_shareholder` set to true enters directly as a `SHAREHOLDER` holding `initial_shares` — which must then be at least 1 — and those shares are debited from treasury; if the treasury does not hold enough shares the onboarding is rejected with `ERR_INSUFFICIENT_TREASURY_SHARES`. Any other physician enters as an `ASSOCIATE` with zero shares.

Each physician evolves along two parallel state dimensions that never interact. The `partnership_status` dimension runs `ASSOCIATE` → `PARTNER_TRACK` → `SHAREHOLDER` → `EXITING` → `EXITED`, with a direct `ASSOCIATE` → `SHAREHOLDER` path; `EXITED` is terminal, and an `EXITED` physician is immutable — any attempted mutation is rejected with `ERR_INVALID_STATE`. The `standing` dimension starts at `GOOD_STANDING` and moves freely among `GOOD_STANDING`, `PROBATION`, and `SUSPENDED` at a `BoardAdmin`'s direction — the standing-update call takes the target `standing` value and an optional `note` — with one restriction: standing cannot be changed on an `EXITED` physician (`ERR_INVALID_STATE`). The system itself also moves standing: the default cascade described in §3.6 suspends a physician whose assessment defaults, whether they were in `GOOD_STANDING` or `PROBATION`.

Three computed quantities ride on each physician row. `shares_held` is the current voting share count, meaningful for the `SHAREHOLDER` tier only. `capital_account_balance_cents` is a ledger that increases with assessment payments, decreases with paid distribution allocations, increases with clawback compensation, and is permitted to go negative. `ownership_pct` is the physician's `shares_held` divided by total shares outstanding — the sum of `shares_held` across all physicians whose `partnership_status` is not `EXITED` — rounded half-up to 6 decimal places, and defined as 0 when no shares are outstanding. This recalculation runs whenever any physician's `shares_held` mutates: founding creation, buy-in completion, or exit finalization. Treasury shares follow the companion rule: `total_shares_authorized` minus the sum of `shares_held` over all physicians (an `EXITED` physician holds zero, so the two sums coincide in practice). `tenure_years` is the number of full 365.25-day years elapsed between `hire_date` and the logical clock.

An `EXITING` physician is in a wind-down state and is blocked from two activities: receiving new buy-in offers and sponsoring motions — both are rejected with `ERR_PHYSICIAN_EXITING`.

### 3.2. The Buy-In Offer and the Partner Track

A `BoardAdmin` extends a buy-in offer by supplying `physician_id`, `target_tier`, `share_grant`, and `installment_count`. The target tier is `PARTNER_TRACK` when the offeree is an `ASSOCIATE`, or `SHAREHOLDER` when the offeree is an `ASSOCIATE` or `PARTNER_TRACK`. For a `SHAREHOLDER` offer, `share_grant` must be greater than 0; for a `PARTNER_TRACK` offer it must be exactly 0. `installment_count` is between 1 and 5 inclusive. A physician may hold at most one offer whose acceptance window is still open — the window is a closed interval — so creating a second offer while an `OFFERED` offer's window remains open is rejected with `ERR_OFFER_WINDOW_OVERLAP`.

At creation the server snapshots `offered_at` from the logical clock and computes the full price. Tenure at offer time, `tenure_years_at_offer`, is the full 365.25-day years between the physician's `hire_date` and `offered_at`. The discount percentage, `discount_pct_applied`, is the smaller of `tenure_years_at_offer` multiplied by `tenure_discount_pct_per_year` and `max_tenure_discount_pct` — with the defaults, 2 percent per year of tenure, capped at 20 percent. The tier base is `buy_in_base_shareholder_cents` for a `SHAREHOLDER` target or `buy_in_base_partner_cents` for a `PARTNER_TRACK` target. Proration works in twelfths of the fiscal year: the fiscal month index counts months from the fiscal year start, so an offer made in July (the fiscal year start under the default `fiscal_year_start_month` of 7) has `proration_twelfths` of 12 and an offer made in June has `proration_twelfths` of 1. The discounted base is the tier base multiplied by one minus the discount percentage; the prorated amount is the discounted base multiplied by `proration_twelfths` and divided by 12, rounded half-up to whole cents — the only rounding step in this calculation. `final_amount_cents` is the prorated amount, but never below `min_buy_in_cents`. The `installment_schedule_cents` splits the final amount into `installment_count` equal parts by flooring, with the remainder cents placed on the first installment — so the first entry is the floor plus the residue and every later entry is the floor. The `acceptance_deadline` is `offered_at` plus `offer_window_days`, and the interval is closed: acceptance is allowed at the deadline instant itself, and the clock sweep expires the offer only once the clock is strictly past the deadline.

The offer starts `OFFERED`. The offeree — and only the offeree, as a `Physician` caller acting on their own offer — responds with a `decision` of `ACCEPT` or `DECLINE`. Acceptance moves the offer to `ACCEPTED` and activates the installment schedule; declining moves it to `DECLINED`. Responding to an offer that is no longer `OFFERED` is rejected with `ERR_OFFER_NOT_OPEN` — and because the sweep expires offers atomically with the clock-set, a past-deadline offer is already `EXPIRED` by the time any response could arrive.

Each installment payment carries `amount_cents` and must equal the scheduled installment amount exactly; anything else is rejected with `ERR_INSTALLMENT_AMOUNT_MISMATCH`. The offer must be `ACCEPTED` to accept payment, otherwise `ERR_OFFER_NOT_OPEN`. Either the physician or a `BoardAdmin` may pay. Each payment increments `paid_installment_count`. When the final installment lands — `paid_installment_count` reaching `installment_count` — the offer completes, and the physician's tier advances: to `PARTNER_TRACK` with no shares issued for a partner-track offer, or to `SHAREHOLDER` for a shareholder offer, in which case the treasury must hold at least `share_grant` shares (`ERR_INSUFFICIENT_TREASURY_SHARES` otherwise), the physician's `shares_held` increases by `share_grant`, and `treasury_shares` decreases by the same amount. Both the physician and the offer increment their `version` at completion.

### 3.3. Board Seats and Committees

The board is a fixed set of `BoardSeat` records created by a `BoardAdmin` with a `seat_label` and a `seat_class` of `CLINICAL`, `AT_LARGE`, or `EX_OFFICIO`, starting `VACANT`. Appointment semantics depend on the seat's current state. Appointing into a `VACANT` seat requires the holder physician to be a `SHAREHOLDER` who is not `SUSPENDED` (`ERR_INVALID_STATE`), and the term window must be well-formed: `term_end` strictly after `term_start` (`ERR_TERM_WINDOW_INVALID`). The appointment sets `current_holder_physician_id`, `current_term_start`, and `current_term_end`, and the seat becomes `FILLED`. Terms are half-open intervals: the holder serves from `current_term_start` inclusive to `current_term_end` exclusive.

Appointing into an already `FILLED` seat books a successor rather than replacing the incumbent. The same eligibility and window checks apply to the successor. Two additional rules govern succession: only one successor may be booked at a time (`ERR_SUCCESSOR_ALREADY_BOOKED`), and the successor's window must not overlap the current term — `next_term_start` must be at or after `current_term_end`, so adjacency is allowed but true overlap is rejected with `ERR_SEAT_TERM_OVERLAP`. A booked successor is recorded as `next_holder_physician_id`, `next_term_start`, and `next_term_end`. The clock sweep at a term's end promotes the booked successor to current holder and clears the successor fields; with no successor booked, the seat falls `VACANT` and the current holder is cleared. When a partner exit finalizes, a seat the exiting physician holds is vacated — unless a successor is booked, in which case the successor is promoted and the seat stays `FILLED`.

Committees are chartered by a `BoardAdmin` with a `name`, a `committee_type` of `QUALITY`, `FINANCE`, or `COMPENSATION`, and two charter fields: `quorum_count`, the minimum number of active members for the committee to transact, and `approval_threshold`, either `SIMPLE_MAJORITY` or `SUPERMAJORITY`. A new committee is `CHARTERED` with `charter_version` 1 and an empty `members` list. Members are embedded entries — each carries a `physician_id`, a `committee_role` of `CHAIR` or `MEMBER`, and the `added_at` instant — not a separate entity. Adding a member is rejected when the committee already has `max_committee_members` members (`ERR_COMMITTEE_FULL`), when a `CHAIR` is added to a committee that already has one (`ERR_CHAIR_ALREADY_ASSIGNED`), or when the physician is already a member (`ERR_DUPLICATE_MEMBERSHIP`). Member operations on a `DISSOLVED` committee are rejected with `ERR_INVALID_STATE`.

Committee status is a compound, derived from `active_member_count` — the length of the members list — against `quorum_count`. Adding members until the count reaches quorum moves the committee from `CHARTERED` to `ACTIVE`; a removal that drops the count below quorum moves it from `ACTIVE` to `IMPAIRED`, and adding back to quorum restores it from `IMPAIRED` to `ACTIVE`. A charter amendment that raises `quorum_count` above the current `active_member_count` also impairs an `ACTIVE` committee. Dissolution is available from `CHARTERED`, `ACTIVE`, or `IMPAIRED` — but only while no motion referencing the committee sits in `OPEN` or `TABLED` status, otherwise `ERR_INVALID_STATE` — and clears the members list as the committee becomes `DISSOLVED`.

### 3.4. Motions and Voting

Any shareholder in good standing may sponsor a motion. A motion is created with `motion_type` — one of `CHARTER_AMENDMENT`, `COMP_POLICY`, `CAPITAL_CALL`, `DISTRIBUTION`, `BUYOUT_APPROVAL`, or `MERGER` — plus `sponsor_physician_id` and a type-specific `payload`. When a `Physician` sponsors, `sponsor_physician_id` must equal the caller's `X-User-ID`; a `BoardAdmin` may sponsor on a physician's behalf by supplying the id in the body. The sponsor must be a `SHAREHOLDER` in `GOOD_STANDING` both at creation and again at propose time and open time — a sponsor whose standing has lapsed blocks the transition with `ERR_INVALID_STATE`. `CHARTER_AMENDMENT` motions must reference a `committee_id`; other types may omit it. A client-supplied `threshold_type` is an unknown field and rejected with `ERR_INVALID_REQUEST`: `threshold_type` is always computed from the motion type — `SIMPLE_MAJORITY` for `CAPITAL_CALL`, `DISTRIBUTION`, and `COMP_POLICY`; `SUPERMAJORITY` for `CHARTER_AMENDMENT`, `BUYOUT_APPROVAL`, and `MERGER`.

The `payload` shape is pinned by type. `CAPITAL_CALL` carries `amount_cents`, `due_date`, and `purpose`; the due date must be strictly after the clock at motion creation (`ERR_INVALID_REQUEST`). `DISTRIBUTION` carries `amount_cents`, `method` (`PRO_RATA` or `SENIORITY_TIERED`), and `fiscal_net_income_before_bonus_cents`. `CHARTER_AMENDMENT` carries optional `new_quorum_count` and `new_approval_threshold`. `COMP_POLICY` carries `new_bonus_pool_pct`. `BUYOUT_APPROVAL` carries `exit_valuation_id`. `MERGER` carries `merger_proposal_id`. Missing type-required sub-fields fail validation with `ERR_INVALID_REQUEST`, and the referenced foreign keys — `exit_valuation_id`, `merger_proposal_id`, `supersedes_motion_id`, `committee_id` — must resolve or the create fails with `ERR_NOT_FOUND`.

A new motion is `DRAFT`. It moves to `PROPOSED`, then to `OPEN`. Opening snapshots the eligible electorate: `eligible_voter_ids` is the set of physicians who are `SHAREHOLDER` and `GOOD_STANDING` at that instant, `opened_at` is set to the clock, and `closes_at` to the clock plus `voting_window_days`. Opening a `CHARTER_AMENDMENT` has one extra gate: the referenced committee must be `ACTIVE`, otherwise `ERR_COMMITTEE_IMPAIRED`. An `OPEN` motion may be tabled — voting pauses, cast votes are retained — and a `TABLED` motion may be resumed, which restarts the window fresh: `opened_at` resets to the clock and `closes_at` to the clock plus `voting_window_days` again. Withdrawal is available from `DRAFT`, `PROPOSED`, or `TABLED`. A new motion may also name `supersedes_motion_id`; if the target motion is `DRAFT` or `PROPOSED` it becomes `SUPERSEDED`, while superseding a motion in any later or terminal state is rejected with `ERR_MOTION_TERMINAL`. The clock sweep expires `OPEN` and `TABLED` motions once the clock passes `closes_at`.

Ballots are cast by physicians with a `vote_choice` of `FOR`, `AGAINST`, or `ABSTAIN`, with the voter taken from `X-User-ID`. A ballot is accepted only while the motion is `OPEN` (`ERR_MOTION_NOT_OPEN`), only while the clock is strictly before `closes_at` (`ERR_VOTING_CLOSED`), only from a physician in the eligible snapshot whose standing is still `GOOD_STANDING` at cast time (`ERR_VOTER_INELIGIBLE`), only once per physician per motion (`ERR_DUPLICATE_VOTE`), and only past three compliance gates: the voter must not appear in `recused_physician_ids` for this motion (`ERR_VOTER_RECUSED`); the voter must not have an unreviewed `FILED` disclosure related to this motion (`ERR_COI_REVIEW_PENDING`); and segregation of duties forbids the sponsor from voting on their own `COMP_POLICY` motion, and forbids the `CHAIR` of the `COMPENSATION` committee from sponsoring a `COMP_POLICY` motion at all (`ERR_SEGREGATION_OF_DUTIES`). Each cast vote recomputes the motion's tallies and bumps the motion's `version`. A `Physician` may only cast for themselves.

Closing a motion is a `BoardAdmin` act with two gates, checked in order. First quorum: the count of non-voided ballots cast — of any choice, including `ABSTAIN` — must be at least `board_quorum_count`, otherwise `ERR_QUORUM_NOT_MET`. Second the threshold, which depends on `threshold_type`. For `SUPERMAJORITY`, `eligible_voter_count` is the snapshot size minus the recused count, `required_votes` is `supermajority_num` divided by `supermajority_den` multiplied by `eligible_voter_count` and rounded up to a whole ballot, and the motion is `ADOPTED` when `votes_for` is at least `required_votes` — equality adopts. For `SIMPLE_MAJORITY`, `required_votes` is an informational 0, and the motion is `ADOPTED` when `votes_for` strictly exceeds `votes_against`; a tie rejects. `votes_for`, `votes_against`, and `votes_abstain` count only non-`VOIDED` ballots. A motion that meets quorum but not its threshold becomes `REJECTED`.

Adoption has type-specific effects. An adopted `CAPITAL_CALL` creates a `CapitalCall` in `APPROVED` status with `total_amount_cents`, `purpose`, and `due_date` from the payload. An adopted `DISTRIBUTION` re-checks that at least one eligible shareholder exists — `SHAREHOLDER` exactly, not suspended — failing with `ERR_NO_ELIGIBLE_RECIPIENTS` (the same check also runs at motion creation), then creates a `Distribution` in `APPROVED` status with allocations computed per §3.5. An adopted `CHARTER_AMENDMENT` applies `new_quorum_count` and `new_approval_threshold` to the referenced committee, increments `charter_version` by 1, and impairs the committee if the new quorum exceeds its active membership. An adopted `COMP_POLICY` writes `new_bonus_pool_pct` onto the policy's `bonus_pool_pct`, increments `comp_policy_version` by 1, and bumps the policy's `version`. Adopted `BUYOUT_APPROVAL` and `MERGER` motions have no direct effect at adoption; they are consumed later by exit finalization and merger decision respectively, matched by the payload ids.

### 3.5. Money In, Money Out: Capital Calls and Distributions

A `CapitalCall` begins life `APPROVED` when its motion is adopted. Billing is a separate `BoardAdmin` act that snapshots the shareholder base — physicians whose `partnership_status` is exactly `SHAREHOLDER` at billing time, of any standing, with `EXITING` and `EXITED` excluded — and creates one `CapitalCallAssessment` per shareholder, each linked back to its call by `capital_call_id` and to the assessed physician by `physician_id`. Each assessment pins `shares_at_billing` from the snapshot and computes `assessed_cents` share-weighted: the raw amount is the call's `total_amount_cents` multiplied by the shareholder's shares and divided by total snapshot shares; each assessment is floored, and the residual pennies go one cent each to the largest holders by `shares_held`, ties broken by the physician's `created_at` ascending. The call's `assessed_total_cents` is the sum of the assessments, and billing moves the call from `APPROVED` to `BILLED`. Note the deliberate asymmetry with distributions: suspended shareholders are still assessed by capital calls.

An assessment starts `BILLED`. Payments carry `amount_cents` and may be partial or full, made by the assessed physician or a `BoardAdmin`. A payment below the remaining `total_due_cents` moves the assessment to `PARTIAL`; one that brings `paid_cents` exactly to `total_due_cents` moves it to `PAID` — and an amount equal to the remaining due always succeeds, while anything above the remaining due is rejected with `ERR_OVERPAYMENT`. Paying into a `PAID` or `DEFAULTED` assessment is rejected with `ERR_ASSESSMENT_NOT_PAYABLE`. Every payment adds the amount to the physician's `capital_account_balance_cents` and recomputes the call's `collected_cents` as the sum of `paid_cents` across its assessments; when every assessment is `PAID` the call bubbles up to `COLLECTED`.

The clock sweep drives the delinquency ladder. An assessment not fully paid once the clock passes its `due_date` becomes `DELINQUENT`, and the late fee — `late_fee_cents`, computed as `assessed_cents` multiplied by `late_fee_pct` and rounded half-up — is applied exactly once; re-sweeps never compound it, so `total_due_cents` becomes `assessed_cents` plus the one-time fee. A `DELINQUENT` assessment can still be paid, now against the fee-inclusive total. Once the clock passes `due_date` plus `delinquency_grace_days` — strictly; at exactly that instant the assessment is still `DELINQUENT` — the assessment becomes `DEFAULTED`, and the cascade fires: the physician's `standing` moves to `SUSPENDED` from either `GOOD_STANDING` or `PROBATION`, and if no payable assessments remain on the call — every other assessment being `PAID` or `DEFAULTED` — the call bubbles up to `PARTIALLY_DEFAULTED`.

Distributions mirror the shape but not the rules. A `Distribution` is created `APPROVED` at motion adoption with `total_amount_cents`, `method`, and `fiscal_net_income_before_bonus_cents` from the payload. Two guardrails are computed at adoption. First the bonus accrual: `bonus_accrual_cents` is `fiscal_net_income_before_bonus_cents` multiplied by `bonus_pool_pct`, rounded half-up. Then the cap: `distributable_cap_cents` is the remaining income after the bonus accrual, multiplied by `distribution_cap_pct`, rounded half-up. The evaluation order is pinned — the bonus accrual is computed from pre-bonus net income first, and the cap applies to the remainder; computing the cap directly on pre-bonus income produces a different, wrong result. The motion's `amount_cents` must not exceed `distributable_cap_cents`, checked both at motion creation and again at adoption; an excess is rejected with `ERR_DISTRIBUTION_CAP_EXCEEDED`.

The allocation set is physicians whose `partnership_status` is exactly `SHAREHOLDER` and whose standing is not `SUSPENDED` — `EXITING` and `EXITED` are excluded. Under the `PRO_RATA` method, each eligible physician's raw allocation is the total amount multiplied by their `shares_held` and divided by total eligible shares; each allocation is floored, and the residual pennies go one cent at a time to the physicians with the most shares, ties broken by `created_at` ascending. Under the `SENIORITY_TIERED` method there are two stages, in pinned order. First the carve: `seniority_carve_pct` of the total, rounded half-up, is split equally among the seniors — eligible physicians whose `tenure_years` is at least `seniority_tier_years` — each floored, with carve residual pennies going one each in `created_at` ascending order. If no physician qualifies as senior, the carve stage is skipped and the entire total is allocated pro-rata. Second, the remainder after the carve is allocated pro-rata across all eligible physicians under the same floor-and-residual rule as `PRO_RATA`. The same inputs therefore produce different per-physician amounts under the two methods. The allocations live in the distribution's embedded `allocations` list: each entry carries a `physician_id` — a plain reference — an `allocated_cents`, and a status of `PENDING`, `PAID`, `CLAWED_BACK`, or `CANCELLED`.

A `BoardAdmin` disburses one `PENDING` allocation at a time: the allocation becomes `PAID` and the physician's `capital_account_balance_cents` decreases by `allocated_cents`. When every allocation is `PAID`, the distribution bubbles up to `PAID`. Voiding works from either `APPROVED` or `PAID`: every `PENDING` allocation becomes `CANCELLED`, every `PAID` allocation becomes `CLAWED_BACK` with the `allocated_cents` added back to the physician's capital account as compensation, and the distribution becomes `VOIDED`.

### 3.6. Partner Exit and Buy-Out Valuation

A partner exit begins when a `Physician` initiates their own exit, or a `BoardAdmin` initiates on their behalf, by supplying `physician_id` and a `trigger_type` of `VOLUNTARY`, `RETIREMENT`, `TERMINATION`, or `DEATH`. Only one non-terminal valuation may exist per physician — a second initiation while one is in flight is rejected with `ERR_EXIT_ALREADY_IN_PROGRESS`. This in-flight check is evaluated before the partnership-state gate: initiation always moves the physician to `EXITING`, so running the state gate first would make the in-flight rejection unreachable. A physician with no valuation in flight must be a `SHAREHOLDER` to initiate; initiating for a physician in any other partnership status is rejected with `ERR_INVALID_STATE`. Initiation pins `ownership_pct_snapshot` — the physician's exact ownership fraction at that instant, displayed at 6 decimal places and never re-opened by later share changes — and computes `provisional_value_cents`, the book-style estimate: the physician's `capital_account_balance_cents` plus their ownership snapshot multiplied by `trailing_ebitda_cents` and by `ebitda_multiple`, that product rounded half-up to cents. The physician's `partnership_status` moves from `SHAREHOLDER` to `EXITING` at initiation, and the valuation starts at `INITIATED`.

Appraisal is a `BoardAdmin` act carrying `appraised_practice_value_cents` and, per §2.6, `expected_valuation_version`. Recording the first appraisal moves the valuation from `INITIATED` to `APPRAISED` and computes `final_value_cents`. A corrected appraisal may be recorded while `APPRAISED` — it supersedes the prior value and recomputes `final_value_cents` — and a re-appraisal may be recorded from `DISPUTED` with the same effect. From `ARBITRATION`, the appraisal recorded is the arbitrator's value: it marks `appraisal_final` true, which blocks all further disputes. The final value depends on the trigger: for `VOLUNTARY` and `RETIREMENT` exits it is the appraised practice value multiplied by the ownership snapshot and by one minus `minority_discount_pct`, rounded half-up; for `TERMINATION` and `DEATH` the minority discount is waived, so it is simply the appraised practice value multiplied by the ownership snapshot, rounded half-up.

The exiting physician — and only that physician — may dispute an appraisal, moving the valuation from `APPRAISED` to `DISPUTED` and incrementing `dispute_rounds` by 1. Disputes are blocked once `appraisal_final` is true (`ERR_INVALID_STATE`) and capped at `max_dispute_rounds` rounds: when `dispute_rounds` has reached the cap, another dispute is rejected with `ERR_DISPUTE_LIMIT_REACHED`, and arbitration is the only path forward. The cap rejection presupposes an otherwise-valid dispute: the state and finality gates run first, so a dispute attempted from any status other than `APPRAISED`, or while `appraisal_final` is true, is rejected with `ERR_INVALID_STATE` regardless of the current `dispute_rounds`. A `BoardAdmin` moves a `DISPUTED` valuation into `ARBITRATION`.

Finalization is a `BoardAdmin` act carrying `motion_id`. The referenced motion must be an `ADOPTED` `BUYOUT_APPROVAL` motion whose payload's `exit_valuation_id` names this valuation, and it must not already have been consumed by another finalize — otherwise `ERR_BUYOUT_NOT_APPROVED`. The valuation must also be `APPRAISED` to finalize, otherwise `ERR_VALUATION_NOT_APPRAISED`. Finalization sets `approving_motion_id`, computes `payment_schedule_cents` — 40 percent of `final_value_cents` at finalization, 30 percent at plus 12 months, 30 percent at plus 24 months, the first two entries rounded half-up and the last entry absorbing the rounding residue — and fires the exit cascade in three links. First, the physician moves from `EXITING` to `EXITED`, `shares_held` goes to 0, and the returned shares flow back to `treasury_shares`. Second, any board seat the physician holds is vacated — or its booked successor is promoted. Third, the physician's committee memberships are removed, and any committee that falls below quorum becomes `IMPAIRED`; this impairment re-check cascades through the affected committees.

### 3.7. Conflict-of-Interest Disclosure and the Recusal Cascade

Any physician files a conflict-of-interest disclosure with a `description` and optionally a `related_motion_id`; the filer is the `X-User-ID` physician, and the disclosure starts `FILED`. Review is exclusively a `ComplianceOfficer` act, carrying an `outcome` of `CLEARED` or `FLAGGED` and an optional `review_note`; the reviewer's `X-User-ID` is recorded as `reviewed_by`. A `CLEARED` outcome has no recusal effect. A `FLAGGED` outcome fires a two-link cascade when `related_motion_id` is set and that motion is `OPEN` or `TABLED`: first the physician is added to the motion's `recused_physician_ids`, which recomputes `eligible_voter_count` and `required_votes`; second, any `CAST` vote by that physician on that motion becomes `VOIDED` with `void_reason` set to `COI_RECUSAL`, and the motion's tallies are recomputed excluding it. If the related motion is already terminal, the flag is recorded but no recusal cascade runs.

The disclosure also gates future ballots: a physician with a `FILED` disclosure related to a motion cannot vote on it until review completes (`ERR_COI_REVIEW_PENDING`), and a physician recused by a `FLAGGED` disclosure cannot vote on it at all (`ERR_VOTER_RECUSED`).

### 3.8. Merger and Affiliation Proposals

A `BoardAdmin` registers a merger proposal with `counterparty_name`, `exchange_ratio_x1000` — the share exchange ratio multiplied by 1000, carried as an integer to avoid float drift — and `cash_consideration_cents`. Only one non-terminal proposal may exist at a time; registering a second while one sits in `PROPOSED`, `DUE_DILIGENCE`, or `NEGOTIATION` is rejected with `ERR_MERGER_ALREADY_ACTIVE`. The proposal starts `PROPOSED` and advances through `DUE_DILIGENCE` to `NEGOTIATION` under a `BoardAdmin`'s hand, recording an optional `diligence_note` on advance.

Deciding a proposal takes an `outcome` and, for the two board-ratified outcomes, a `motion_id`. Approval requires an `ADOPTED` `MERGER` motion whose payload's `merger_proposal_id` names this proposal; rejection requires a `REJECTED` `MERGER` motion naming it; a mismatch on either is rejected with `ERR_MERGER_NOT_APPROVED`. Both set `deciding_motion_id` and move the proposal to `APPROVED` or `REJECTED`. Termination is unilateral: a `TERMINATE` outcome needs no motion and moves the proposal from `PROPOSED`, `DUE_DILIGENCE`, or `NEGOTIATION` to `TERMINATED`.

## 4. Endpoint Definitions

All endpoints live under the `/governance` prefix except the test-driving clock. Creating a new resource returns HTTP 201; operations that modify an existing resource or return reads return HTTP 200.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /governance/policy | Create the singleton governance policy | BoardAdmin |
| GET | /governance/policy | Read the policy | BoardAdmin, Physician, ComplianceOfficer |
| PATCH | /governance/policy | Update policy constants (OCC-guarded) | BoardAdmin |
| POST | /governance/physicians | Onboard a physician (associate by default; founding shareholder when flagged) | BoardAdmin |
| GET | /governance/physicians | List physicians (filters: `partnership_status`, `standing`) | BoardAdmin, Physician, ComplianceOfficer |
| GET | /governance/physicians/{id} | Get a physician | BoardAdmin, Physician, ComplianceOfficer |
| POST | /governance/physicians/{id}/standing | Set standing (PROBATION, SUSPENDED, or restore GOOD_STANDING) | BoardAdmin |
| POST | /governance/board-seats | Create a VACANT board seat | BoardAdmin |
| GET | /governance/board-seats | List board seats (filters: `status`, `current_holder_physician_id`, `next_holder_physician_id`) | BoardAdmin, Physician, ComplianceOfficer |
| GET | /governance/board-seats/{id} | Get a board seat | BoardAdmin, Physician, ComplianceOfficer |
| POST | /governance/board-seats/{id}/appoint | Appoint holder (VACANT seat) or book successor (FILLED seat) | BoardAdmin |
| POST | /governance/committees | Charter a committee | BoardAdmin |
| GET | /governance/committees | List committees (filters: `committee_type`, `status`) | BoardAdmin, Physician, ComplianceOfficer |
| GET | /governance/committees/{id} | Get a committee | BoardAdmin, Physician, ComplianceOfficer |
| POST | /governance/committees/{id}/members | Add a member (CHAIR or MEMBER) | BoardAdmin |
| POST | /governance/committees/{id}/members/{physician_id}/remove | Remove a member | BoardAdmin |
| POST | /governance/committees/{id}/dissolve | Dissolve a committee (blocked while OPEN/TABLED motions reference it) | BoardAdmin |
| POST | /governance/buy-in-offers | Offer buy-in terms; computes price and installment schedule | BoardAdmin |
| GET | /governance/buy-in-offers | List buy-in offers (filters: `physician_id`, `status`) | BoardAdmin, Physician |
| GET | /governance/buy-in-offers/{id} | Get a buy-in offer | BoardAdmin, Physician |
| POST | /governance/buy-in-offers/{id}/respond | Offeree accepts or declines | Physician |
| POST | /governance/buy-in-offers/{id}/pay-installment | Pay the next scheduled installment (exact amount required) | Physician, BoardAdmin |
| POST | /governance/motions | Sponsor a motion; optional supersede | Physician, BoardAdmin |
| GET | /governance/motions | List motions (filters: `sponsor_physician_id`, `committee_id`, `supersedes_motion_id`, `status`) | BoardAdmin, Physician, ComplianceOfficer |
| GET | /governance/motions/{id} | Get a motion (with tallies) | BoardAdmin, Physician, ComplianceOfficer |
| POST | /governance/motions/{id}/propose | Move DRAFT to PROPOSED | Physician, BoardAdmin |
| POST | /governance/motions/{id}/open | Move PROPOSED to OPEN; snapshot electorate and set the voting window | Physician, BoardAdmin |
| POST | /governance/motions/{id}/table | Move OPEN to TABLED | Physician, BoardAdmin |
| POST | /governance/motions/{id}/resume | Move TABLED to OPEN with a fresh voting window | Physician, BoardAdmin |
| POST | /governance/motions/{id}/withdraw | Withdraw a DRAFT, PROPOSED, or TABLED motion | Physician, BoardAdmin |
| POST | /governance/motions/{id}/close | Tally an OPEN motion to ADOPTED or REJECTED | BoardAdmin |
| POST | /governance/motions/{id}/votes | Cast a ballot (voter is the calling physician) | Physician |
| GET | /governance/motions/{id}/votes | List votes on a motion | BoardAdmin, Physician, ComplianceOfficer |
| GET | /governance/physicians/{id}/votes | List votes cast by a physician | BoardAdmin, Physician, ComplianceOfficer |
| GET | /governance/capital-calls | List capital calls (filters: `motion_id`, `status`) | BoardAdmin, Physician, ComplianceOfficer |
| GET | /governance/capital-calls/{id} | Get a capital call | BoardAdmin, Physician, ComplianceOfficer |
| POST | /governance/capital-calls/{id}/bill | Bill the call: snapshot shareholders and create assessments | BoardAdmin |
| GET | /governance/capital-calls/{id}/assessments | List assessments of a call | BoardAdmin, Physician, ComplianceOfficer |
| GET | /governance/physicians/{id}/assessments | List assessments of a physician | BoardAdmin, Physician, ComplianceOfficer |
| POST | /governance/capital-call-assessments/{id}/pay | Pay toward an assessment (partial allowed; overpay rejected) | Physician, BoardAdmin |
| GET | /governance/distributions | List distributions (filters: `motion_id`, `status`) | BoardAdmin, Physician, ComplianceOfficer |
| GET | /governance/distributions/{id} | Get a distribution with allocations | BoardAdmin, Physician, ComplianceOfficer |
| POST | /governance/distributions/{id}/allocations/{physician_id}/pay | Disburse one PENDING allocation | BoardAdmin |
| POST | /governance/distributions/{id}/void | Void a distribution (claw back PAID allocations, cancel PENDING) | BoardAdmin |
| POST | /governance/exit-valuations | Initiate a partner exit; snapshot provisional valuation | Physician, BoardAdmin |
| GET | /governance/exit-valuations | List exit valuations (filters: `physician_id`, `approving_motion_id`, `status`) | BoardAdmin, Physician, ComplianceOfficer |
| GET | /governance/exit-valuations/{id} | Get an exit valuation | BoardAdmin, Physician, ComplianceOfficer |
| POST | /governance/exit-valuations/{id}/appraise | Record or supersede an appraisal (OCC-guarded) | BoardAdmin |
| POST | /governance/exit-valuations/{id}/dispute | Physician disputes the appraisal | Physician |
| POST | /governance/exit-valuations/{id}/arbitrate | Move a DISPUTED valuation to ARBITRATION | BoardAdmin |
| POST | /governance/exit-valuations/{id}/finalize | Finalize buy-out with an adopted BUYOUT_APPROVAL motion | BoardAdmin |
| POST | /governance/coi-disclosures | File a conflict-of-interest disclosure | Physician |
| GET | /governance/coi-disclosures | List COI disclosures (filters: `physician_id`, `related_motion_id`, `status`) | BoardAdmin, Physician, ComplianceOfficer |
| GET | /governance/coi-disclosures/{id} | Get a COI disclosure | BoardAdmin, Physician, ComplianceOfficer |
| POST | /governance/coi-disclosures/{id}/review | Compliance review (CLEARED or FLAGGED; FLAGGED fires the recusal cascade) | ComplianceOfficer |
| POST | /governance/merger-proposals | Register a merger/affiliation proposal (one non-terminal at a time) | BoardAdmin |
| GET | /governance/merger-proposals | List merger proposals (filters: `deciding_motion_id`, `status`) | BoardAdmin, Physician, ComplianceOfficer |
| GET | /governance/merger-proposals/{id} | Get a merger proposal | BoardAdmin, Physician, ComplianceOfficer |
| POST | /governance/merger-proposals/{id}/advance | Advance PROPOSED to DUE_DILIGENCE to NEGOTIATION | BoardAdmin |
| POST | /governance/merger-proposals/{id}/decide | Decide APPROVED or REJECTED (requires matching MERGER motion) or TERMINATE (unilateral) | BoardAdmin |
| POST | /_clock/set_current_utc | Set the logical clock and run all time-based sweeps | BoardAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_INVALID_REQUEST | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_RESOURCE_OWNERSHIP | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_MOTION_NOT_OPEN | 409 |
| ERR_MOTION_TERMINAL | 409 |
| ERR_QUORUM_NOT_MET | 409 |
| ERR_OFFER_NOT_OPEN | 409 |
| ERR_ASSESSMENT_NOT_PAYABLE | 409 |
| ERR_COMMITTEE_IMPAIRED | 409 |
| ERR_VALUATION_NOT_APPRAISED | 409 |
| ERR_BUYOUT_NOT_APPROVED | 409 |
| ERR_MERGER_NOT_APPROVED | 409 |
| ERR_VOTER_INELIGIBLE | 409 |
| ERR_VOTER_RECUSED | 409 |
| ERR_COI_REVIEW_PENDING | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_VOTING_CLOSED | 409 |
| ERR_TERM_WINDOW_INVALID | 409 |
| ERR_DUPLICATE_VOTE | 409 |
| ERR_SEAT_TERM_OVERLAP | 409 |
| ERR_SUCCESSOR_ALREADY_BOOKED | 409 |
| ERR_OFFER_WINDOW_OVERLAP | 409 |
| ERR_COMMITTEE_FULL | 409 |
| ERR_CHAIR_ALREADY_ASSIGNED | 409 |
| ERR_DUPLICATE_MEMBERSHIP | 409 |
| ERR_DISPUTE_LIMIT_REACHED | 409 |
| ERR_MERGER_ALREADY_ACTIVE | 409 |
| ERR_POLICY_ALREADY_EXISTS | 409 |
| ERR_PHYSICIAN_EXITING | 409 |
| ERR_NO_ELIGIBLE_RECIPIENTS | 409 |
| ERR_EXIT_ALREADY_IN_PROGRESS | 409 |
| ERR_OVERPAYMENT | 409 |
| ERR_DISTRIBUTION_CAP_EXCEEDED | 409 |
| ERR_INSUFFICIENT_TREASURY_SHARES | 409 |
| ERR_INSTALLMENT_AMOUNT_MISMATCH | 409 |
