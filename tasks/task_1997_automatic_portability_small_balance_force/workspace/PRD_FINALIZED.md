# Automatic Portability & Small-Balance Force-Out API — Product Requirements Document

## 1. Introduction

When an employee separates from an employer with a small retirement balance, the plan is permitted — and often prefers — to force the money out. What happens next depends on the size of the vested balance: the smallest balances may be cashed out without consent, mid-sized balances must be rolled into a safe harbor IRA when the participant does not respond, and the largest balances cannot be forced out at all. This document specifies the API of a safe harbor IRA provider that operates this force-out machinery on behalf of employer plans and their recordkeepers, and that additionally runs an automatic portability network: when a forced-out participant later surfaces in a new employer's plan at a participating recordkeeper, the provider matches the two and moves the money again — plan to plan — instead of leaving it stranded.

The API covers the complete lifecycle: balance thresholds and force-out eligibility determination at batch lock; participant notice with a thirty-day election window; establishment of safe harbor IRAs for non-responders, invested in a principal-preservation default vehicle; fee disclosure and periodic maintenance-fee assessment; match-and-transfer into the new employer plan when the participant is found; unclaimed and uncashed check remediation, including reissue and escheatment to the state; recordkeeper network participation with cascading effects when a recordkeeper leaves; and an independent fiduciary review of every reconciled batch, with segregation of duties between the operator who executed a batch and the reviewer who attests it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. The system recognizes exactly four roles: `Participant`, `PlanSponsor`, `ProviderOps`, and `FiduciaryReviewer`. A request missing either header, or presenting a role outside this list, is rejected with `ERR_UNAUTHENTICATED`. A caller whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant` record; ownership checks on any resource that references a participant — submitting or voiding an election, closing an IRA, patching a participant's own address — compare the resource's `participant_id` (or, for the participant record itself, its own `id`) against `X-User-ID`, and a mismatch is rejected with `ERR_PARTICIPANT_OWNERSHIP_MISMATCH`. When `X-User-Role` is `PlanSponsor`, `ProviderOps`, or `FiduciaryReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `executed_by_user_id` on a batch or `reviewer_user_id` on a review — but never compares it to an entity `id`.

One cross-role constraint deserves emphasis: segregation of duties. The `FiduciaryReviewer` who opens a review of a batch must not be the operator who executed that batch; the check compares the reviewer's `X-User-ID` to the batch's `executed_by_user_id` and rejects equality with `ERR_SEGREGATION_OF_DUTIES`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

List endpoints also accept exact-match filter parameters, each named after a resource field and matching resources whose like-named field equals the supplied value. The available filters across the API are `network_status`, `recordkeeper_id`, `plan_status`, `ssn_hash`, `address_quality`, `plan_id`, `batch_status`, `distribution_batch_id`, `participant_id`, `case_status`, `distribution_case_id`, `notice_type`, `delivery_status`, `destination_plan_id`, `election_status`, `ira_status`, `safe_harbor_ira_id`, `check_status`, `supersedes_check_id`, `origin`, `new_plan_id`, `new_recordkeeper_id`, `match_status`, `match_candidate_id`, `transfer_status`, and `review_status`; §4 indicates which filters each list endpoint supports.

### 2.4. The Logical Clock and Deterministic Time

Every deadline, staleness test, dormancy test, and fee accrual in the system reads a single logical clock — never wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`. A `ProviderOps`-only test-driving capability sets the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; setting the clock mutates no entity, and time-driven transitions are applied only by the deterministic sweep described in §3.8. Once set, the clock holds its value until set again and never falls back to wall-clock time.

### 2.5. Common Resource Properties and the Append-Only Fee Ledger

All primary resources share a standard set of system-managed fields:

- **`id` (string):** a unique, server-generated identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording the last modification.
- **`version` (integer):** a system-managed integer that increments by exactly one on every successful mutation of the resource; `updated_at` refreshes on the same event.

The fee ledger is the sole exception. An `IRAFeeAssessment` row is append-only: it carries `id` and `created_at` only, has neither `updated_at` nor `version`, and is never modified after posting. All datetimes everywhere in the API are ISO 8601 UTC with three fractional digits.

### 2.6. Monetary Representation, Rounding, and Day-Count Conventions

All monetary values are integer cents — a check amount, a balance, and a fee are all whole numbers of cents. All rates are decimal fractions: a `state_withholding_rate` of 0.05 means five percent, and match-signal weights are decimal fractions as well. Every monetary rounding in the system is round half-up to integer cents, and the one non-monetary rounding — the `match_score` — is round half-up to three decimal places.

Two day-count conventions govern IRA fee accrual, selected per IRA by `fee_day_count_convention`. Under `ACTUAL_365`, the accrual counts real calendar days and divides the year into 365 parts. Under `THIRTY_360`, every month counts as thirty days and the year as 360. The full accrual arithmetic, including the pinned evaluation order, is specified in §3.6.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each keyed to the version of the resource it acts upon:

1. Updating a plan's force-out configuration requires the request to carry `expected_plan_version` equal to the plan's current `version`.
2. Submitting an election against a case requires `expected_case_version` equal to the case's current `version`.
3. Initiating an IRA transfer requires `expected_ira_version` equal to the IRA's current `version`.

In each case, a mismatch means the client is acting on a version it has not observed; the request is rejected with `ERR_STALE_VERSION` and HTTP status 412, and the client must re-read the resource and re-apply its intent to the current version. Endpoints not listed here do not accept a version field at all.

### 2.8. Recordkeeper Network Status and Cross-Entity Cascades

A plan's `network_reachable` flag is derived, never stored by hand: it is true exactly when the plan's recordkeeper has `network_status` `ACTIVE` and the plan's own `accepts_incoming_transfers` flag is true. The flag is recomputed whenever the recordkeeper's status changes and whenever the plan itself is updated.

Because matching and transfers route through the network, a recordkeeper leaving the network propagates outward in a fixed three-link cascade. First, every plan of that recordkeeper has `network_reachable` recomputed to false. Second, every match candidate still in `CANDIDATE` or `CONFIRMED` whose new-employer plan just lost reachability transitions to `EXPIRED`. Third, every safe harbor IRA sitting in `MATCHED` on one of those just-expired confirmed matches returns to `OPEN`, with its `last_activity_at` deliberately left unchanged so dormancy accounting is not disturbed by an event the participant could not control. The same recompute-to-false happens to a plan that is terminated, though without any match or IRA cascade.

### 2.9. Validation Order and Error Precedence

Every request is evaluated against eleven tiers of checks in a fixed order, and the first failing tier produces the response. Because authentication outranks request shape and shape outranks existence, a request that fails several tiers always reports the earliest failure.

1. **Authentication presence** — `X-User-ID` and `X-User-Role` must be present and the role must be a declared role, on every endpoint; failure is `ERR_UNAUTHENTICATED` (401).
2. **Role authorization** — the caller's role must appear in the endpoint's authorized list; failure is `ERR_FORBIDDEN_ROLE` (403).
3. **Participant ownership** — on participant-scoped calls (case elections and voids, IRA close, a participant patching their own record), `X-User-ID` must equal the target resource's `participant_id`; failure is `ERR_PARTICIPANT_OWNERSHIP_MISMATCH` (403).
4. **Request shape** — required fields present, types valid, enum values in range (`election_type`, `notice_type`, `void_reason`, `outcome`, and similar); failure is `ERR_INVALID_REQUEST` (400).
5. **Existence** — path identifiers and body foreign-key references (plan, batch, case, notice, election, IRA, check, match, transfer, review, recordkeeper, participant) must exist; failure is `ERR_NOT_FOUND` (404).
6. **State permits the transition** — the target entity's current state must allow the requested transition, including state guards such as an IRA not being `MATCHED` or a case not being `NOTIFIED`; failure is `ERR_INVALID_STATE` (409).
7. **Compliance gates** — segregation of duties on review creation, fee disclosure before fee assessment, prenotice delivery before transfer, the escheat-warning lead time, and no unnoticed case at batch execute; failures are `ERR_SEGREGATION_OF_DUTIES`, `ERR_FEE_DISCLOSURE_NOT_DELIVERED`, `ERR_PRENOTICE_NOT_DELIVERED`, `ERR_ESCHEAT_WARNING_REQUIRED`, and `ERR_CASE_NOTICE_OUTSTANDING` (all 422).
8. **Temporal windows** — the election window must be open, the prenotice opt-out window must have elapsed, a check must not be stale when recorded cashed, batch execution must not run with open election windows, and a review's period must be non-empty; failures are `ERR_ELECTION_WINDOW_CLOSED`, `ERR_PRENOTICE_WINDOW_OPEN`, `ERR_CHECK_STALE`, `ERR_CASE_WINDOW_STILL_OPEN`, and `ERR_REVIEW_PERIOD_INVALID` (all 422).
9. **Referenced-entity state** — the plan must be `ACTIVE` for case creation, the recordkeeper `ACTIVE` for matching and transfer, the match's plan-recordkeeper pair must agree, and a destination plan must be reachable; failures are `ERR_PLAN_NOT_ACTIVE`, `ERR_RECORDKEEPER_NOT_ACTIVE`, `ERR_RECORDKEEPER_PLAN_MISMATCH`, and `ERR_DESTINATION_PLAN_NOT_ACCEPTING` (all 422).
10. **Uniqueness and occupancy** — one in-flight batch per plan, one fee assessment per IRA per month, no overlapping review periods, and the OCC stale-version check; failures are `ERR_DUPLICATE_OPEN_BATCH`, `ERR_DUPLICATE_FEE_PERIOD`, and `ERR_REVIEW_PERIOD_OVERLAP` (409), except the stale-version check, which is `ERR_STALE_VERSION` (412).
11. **Money and threshold rules** — threshold configuration sanity on plan update, automatic execution only on the path the lock selected, a positive transfer amount, the match-score floor for manual confirm, and the SSN gate; failures are `ERR_THRESHOLD_CONFIG_INVALID`, `ERR_CASE_BALANCE_INELIGIBLE`, `ERR_INSUFFICIENT_IRA_BALANCE`, `ERR_MATCH_SCORE_BELOW_THRESHOLD`, and `ERR_SSN_GATE_FAILED` (all 422).

### 2.10. Nested and Referenced Resource Retrieval

Requests that carry several resource identifiers — whether in the path or as foreign keys in the body — are validated left to right: the system confirms each identifier in the order it appears and rejects the request with `ERR_NOT_FOUND` (404) at the first identifier that does not correspond to an existing resource, without examining the remaining identifiers.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Network: Recordkeepers and Plans

A `ProviderOps` operator registers each recordkeeper with a `recordkeeper_code`, unique across the recordkeeper registry, and its `legal_name`. New recordkeepers begin `PENDING_ONBOARD`; activation moves `network_status` to `ACTIVE`, and the same activation reinstates a recordkeeper that was previously suspended (`SUSPENDED` → `ACTIVE`). Suspension moves an `ACTIVE` recordkeeper to `SUSPENDED`. Activation recomputes `network_reachable` to true for every plan of that recordkeeper whose `accepts_incoming_transfers` is true — incrementing those plans' `version` values in the process — while suspension recomputes `network_reachable` to false for every plan of the recordkeeper. Each status action also increments the recordkeeper's own `version`.

Exit is terminal. Exiting an `ACTIVE` or `SUSPENDED` recordkeeper moves it to `EXITED`, stamps `exited_at`, increments its `version`, and fires the three-link cascade of §2.8: plans lose reachability, pending and confirmed matches against those plans expire, and IRAs matched on those matches fall back to `OPEN`.

A `PlanSponsor` registers an employer plan with a `plan_name`, a `sponsor_ein`, and the `recordkeeper_id` of the recordkeeper that houses it. The force-out configuration is optional at registration and defaults as follows: `cash_out_threshold_cents` defaults to 100,000 cents ($1,000), `rollover_threshold_cents` to 700,000 cents ($7,000), `state_withholding_rate` to 0, `valuation_basis` to `PROCESSING_DATE`, and both `auto_portability_enabled` and `accepts_incoming_transfers` to true. The cash-out threshold must be at least 1 cent and no greater than the rollover threshold, and the rollover threshold must be no less than the cash-out threshold; the withholding rate must lie between 0 and 0.15 inclusive. New plans begin with `plan_status` `ACTIVE`, and their `network_reachable` is computed from the rule in §2.8 at creation.

Configuration updates follow the OCC rule of §2.7: the `PlanSponsor` supplies `expected_plan_version` plus any subset of `cash_out_threshold_cents`, `rollover_threshold_cents`, `state_withholding_rate`, `valuation_basis`, `auto_portability_enabled`, and `accepts_incoming_transfers`. An update that would push the cash-out threshold above the rollover threshold, or move the withholding rate outside its bounds, is rejected with `ERR_THRESHOLD_CONFIG_INVALID`; a stale version is rejected with `ERR_STALE_VERSION` (412). A successful update recomputes `network_reachable` and increments the plan's `version`.

Terminating a plan moves `plan_status` from `ACTIVE` to `TERMINATED` and recomputes `network_reachable` to false — the plan no longer accepts or sources activity — but only while no batch of the plan is in flight: a batch in `OPEN`, `LOCKED`, `EXECUTED`, or `RECON_EXCEPTION` blocks termination with `ERR_INVALID_STATE`. Termination increments the plan's `version`.

### 3.2. The Participant Registry and Address Hygiene

Separated participants enter the registry through the census feed, registered by a `PlanSponsor` or `ProviderOps` with an `ssn_hash` — a salted hash of the SSN, unique across the participant registry — plus `full_name`, `date_of_birth` in `YYYY-MM-DD` form, and the mailing address fields `mailing_address_line1`, `mailing_city`, `mailing_state` (a two-letter code), and `mailing_zip`; `email` is optional and defaults to null. New participants start with `address_quality` `UNVERIFIED`.

Address hygiene is tracked on the participant record. Any successful address update — touching `mailing_address_line1`, `mailing_city`, `mailing_state`, `mailing_zip`, or `email`, performed by a `PlanSponsor`, a `ProviderOps` operator, or the participant — marks `address_quality` `VALID` and increments the participant's `version`; a `Participant` caller may only update their own record, and any attempt on another participant is rejected with `ERR_PARTICIPANT_OWNERSHIP_MISMATCH`. Conversely, any notice that comes back `BOUNCED` or `RETURNED_MAIL` marks the participant `BAD_ADDRESS` (§3.4), and a `BAD_ADDRESS` blocks check reissue until repaired (§3.8). The cycle is deliberate: re-noticing a participant whose mail failed requires an address patch first and then a fresh notice.

### 3.3. Assembling and Locking a Force-Out Batch

A force-out run begins when a `PlanSponsor` opens a distribution batch for a plan, supplying the `plan_id`. The plan must be `ACTIVE` — a terminated plan rejects batch creation with `ERR_PLAN_NOT_ACTIVE` — and a plan may have at most one batch in flight at a time: opening a second batch while one exists in `OPEN`, `LOCKED`, `EXECUTED`, or `RECON_EXCEPTION` is rejected with `ERR_DUPLICATE_OPEN_BATCH`. New batches start `OPEN` with `executed_by_user_id`, `locked_at`, `executed_at`, and `reconciled_at` all null.

While the batch is `OPEN`, the sponsor attaches one distribution case per separated participant, supplying `distribution_batch_id`, `plan_id`, `participant_id`, the `separation_date`, and two feed balances: `separation_date_balance_cents`, the account balance as of the separation date, and `processing_date_balance_cents`, the account balance as of batch lock. Both balances must be non-negative, and `vesting_percent` may override its default of 100 with any value from 0 to 100 inclusive. The case's `plan_id` must equal the batch's plan — a mismatch is `ERR_INVALID_REQUEST` — the batch must still be `OPEN`, otherwise `ERR_INVALID_STATE`, and the plan must be `ACTIVE`, otherwise `ERR_PLAN_NOT_ACTIVE`. At creation each case computes a provisional `quoted_balance_cents`: the separation-date balance times the vesting percent divided by one hundred, rounded half-up to integer cents. Every attachment recomputes the batch's `case_count`. New cases start `IDENTIFIED`, with `vested_balance_cents`, `force_out_path`, `executed_path`, and `current_notice_id` all null.

A case can be withdrawn while it is `IDENTIFIED` or `NOTIFIED` — a rehire or a census error — through sponsor cancellation, which moves `case_status` to `CANCELLED`, recomputes the batch counters, and increments the case's `version`.

Locking is the pivot of the run. A `PlanSponsor` locks an `OPEN` batch that holds at least one attached case; locking an empty batch is rejected with `ERR_INVALID_STATE`. At lock, the system finalizes every attached case in two steps. First, valuation: the case's `vested_balance_cents` is the selected balance times `vesting_percent` divided by one hundred, rounded half-up to integer cents — where the selected balance is `separation_date_balance_cents` when the plan's `valuation_basis` is `SEPARATION_DATE`, or `processing_date_balance_cents` when it is `PROCESSING_DATE`. The separation-date variant freezes the balance at separation and ignores market movement between separation and lock; the processing-date variant — the default — uses the balance at lock, so for identical inputs with drifted balances the two variants can produce different vested balances, possibly landing the case in a different force-out band. Second, immediately after valuation, path selection: a `vested_balance_cents` at or below the plan's `cash_out_threshold_cents` takes the `CASH_OUT` path; a balance above the cash-out threshold but at or below the `rollover_threshold_cents` takes `SAFE_HARBOR_IRA`; anything above the rollover threshold is `INELIGIBLE_REMAINS`. The boundaries are inclusive exactly as stated — a balance equal to the cash-out threshold is a cash-out while one cent above it goes to an IRA, and a balance equal to the rollover threshold goes to an IRA while one cent above it remains in the plan. Cases locked into `INELIGIBLE_REMAINS` move straight from `IDENTIFIED` to `SETTLED` with `executed_path` `REMAIN_IN_PLAN`: no notice, no money movement. Locking stamps `locked_at`, recomputes `case_count`, `settled_case_count`, and `total_forced_out_cents`, and increments the batch's `version`.

### 3.4. Notice Delivery and the Participant Election Window

All participant mail runs through notices created by `ProviderOps` against a case, each carrying a `notice_type` of `FORCE_OUT_ELECTION`, `FEE_DISCLOSURE`, `AUTO_PORTABILITY_PRENOTICE`, or `ESCHEAT_WARNING`. Which type may be sent depends on where the case stands, and a violation of these gates is rejected with `ERR_INVALID_STATE`: a `FORCE_OUT_ELECTION` notice requires the case `IDENTIFIED` and its batch `LOCKED`; a `FEE_DISCLOSURE` requires the case in one of `NOTIFIED`, `ELECTED`, `WINDOW_EXPIRED`, `EXECUTED`, or `SETTLED`; an `AUTO_PORTABILITY_PRENOTICE` requires a case that has `SETTLED` through the safe-harbor IRA path; and an `ESCHEAT_WARNING` requires either a case `EXECUTED` with an uncashed check outstanding or a case whose IRA is `OPEN` and drifting toward dormancy. Every notice starts `SENT` with `sent_at` stamped from the logical clock; `delivered_at` and `response_deadline` remain null until delivery is recorded.

Mail-tracking outcomes are recorded per notice with an `outcome` of `DELIVERED`, `BOUNCED`, or `RETURNED_MAIL`; any other value is `ERR_INVALID_REQUEST`, and each recording increments the notice's `version`. Recording `DELIVERED` on a `SENT` notice stamps `delivered_at` and computes the `response_deadline` as thirty days after delivery. When the delivered notice is a `FORCE_OUT_ELECTION` on an `IDENTIFIED` case, the case advances to `NOTIFIED` and adopts that notice as its `current_notice_id` — the window that now governs the case. Recording `BOUNCED` moves the notice to `BOUNCED`, marks the participant `BAD_ADDRESS`, and leaves the case `IDENTIFIED`. Recording `RETURNED_MAIL` — permitted from either `SENT` or `DELIVERED` — also marks the participant `BAD_ADDRESS`, and if the returned notice was the case's `current_notice_id`, the case falls back from `NOTIFIED` to `IDENTIFIED` and clears `current_notice_id`; the participant must be re-addressed and re-noticed before any window can run again.

The election window is inclusive at its upper edge: elections and voids are accepted while the current instant is at or before the current notice's `response_deadline` — a submission at exactly the deadline instant succeeds, and one second later it fails with `ERR_ELECTION_WINDOW_CLOSED`.

While `NOTIFIED` — or already `ELECTED` with the window still open, changing its mind — the participant submits an election with an `election_type` of `LUMP_SUM_CASH`, `SAFE_HARBOR_IRA`, or `DIRECT_ROLLOVER_NEW_PLAN`; `destination_plan_id` is required exactly when the type is `DIRECT_ROLLOVER_NEW_PLAN` and must be null otherwise, a violation being `ERR_INVALID_REQUEST`. The submission must come from the participant who owns the case (`ERR_PARTICIPANT_OWNERSHIP_MISMATCH`), must carry `expected_case_version` matching the case's current `version` (`ERR_STALE_VERSION`, 412), and must arrive within the window. A successful submission stamps `submitted_at`, copies the case's `participant_id` onto the election, starts the election `SUBMITTED`, and moves the case to `ELECTED`; any earlier `SUBMITTED` election of the same case is simultaneously superseded to `SUPERSEDED`, so at most one `SUBMITTED` election exists per case at any time. Each election submission increments the case's `version` — which is precisely why a client holding an older case version must re-read before its election is accepted.

A participant may also revoke. Voiding the case's only `SUBMITTED` election — again within the window, and again only by the owning participant — moves the election to `VOIDED` and returns the case from `ELECTED` to `NOTIFIED` with the window intact; the void increments the election's `version`.

If the deadline passes with no `SUBMITTED` election on the case, the sweep (§3.8) moves the case from `NOTIFIED` to `WINDOW_EXPIRED`, and the force-out path chosen at lock then decides what execution may do with it (§3.5, §3.6).

### 3.5. Executing Distributions: Checks, Withholding, and Direct Rollovers

With every case noticed and every window resolved, `ProviderOps` executes the batch. Execution is blocked while any attached case is still `IDENTIFIED` — its force-out notice was never delivered — and such an attempt is rejected with `ERR_CASE_NOTICE_OUTSTANDING`; it is likewise blocked while any `NOTIFIED` case's window has not yet closed, meaning the current notice's `response_deadline` is at or after the current instant, rejected with `ERR_CASE_WINDOW_STILL_OPEN`. A successful execution moves the batch from `LOCKED` to `EXECUTED`, records the caller's `X-User-ID` as `executed_by_user_id` — the segregation-of-duties anchor for §3.9 — stamps `executed_at`, and increments the batch's `version`.

Three execution paths now distribute the money, and all three remain available whether the batch stands `EXECUTED` or `RECON_EXCEPTION` — remediation never pauses payouts.

For a lump sum, `ProviderOps` issues the cash-out check for a case that is `ELECTED` with a `SUBMITTED` election of type `LUMP_SUM_CASH`, or `WINDOW_EXPIRED` with `force_out_path` `CASH_OUT`; a window-expired case locked into any other path is rejected with `ERR_CASE_BALANCE_INELIGIBLE`, and any other case or batch state is rejected with `ERR_INVALID_STATE`. The check is created with `origin` `CASE_CASH_OUT`, `gross_amount_cents` equal to the case's `vested_balance_cents`, and withholding per the pinned net-check calculation: `fed_withholding_cents` is twenty percent of the gross, rounded half-up to integer cents; `state_withholding_cents` is the gross times the plan's `state_withholding_rate`, rounded half-up to integer cents; and the payable `amount_cents` is the gross minus the two rounded components. The rounding order is pinned — each component is rounded to integer cents first and only then subtracted; netting a combined rate against the gross in a single step is a different, forbidden order that can drift the result by a cent. The check starts `ISSUED`, stamps `issued_at`, and computes `stale_after` as one hundred eighty days after issuance. Issuance moves the case from `ELECTED` (or `WINDOW_EXPIRED`) to `EXECUTED` with `executed_path` `CHECK_CASH_OUT`, moves the election to `EXECUTED`, folds the case's vested balance into the batch's `total_forced_out_cents`, and increments the case's `version`.

For an elected plan-to-plan rollover, a case `ELECTED` with a `SUBMITTED` `DIRECT_ROLLOVER_NEW_PLAN` election is settled directly — no IRA in between — provided the election's destination plan is currently `network_reachable`, otherwise the settlement is rejected with `ERR_DESTINATION_PLAN_NOT_ACCEPTING`. Settlement moves the case to `SETTLED` with `executed_path` `DIRECT_NEW_PLAN`, executes the election, recomputes the batch totals, and increments the case's `version`.

The third path — establishing a safe harbor IRA — is the subject of the next subsection.

### 3.6. Safe Harbor IRA Establishment, Maintenance Fees, and Participant Opt-Out

`ProviderOps` establishes a safe harbor IRA for a case that is `ELECTED` with a `SUBMITTED` `SAFE_HARBOR_IRA` election, or `WINDOW_EXPIRED` with `force_out_path` `SAFE_HARBOR_IRA`; a window-expired case locked into a different path is rejected with `ERR_CASE_BALANCE_INELIGIBLE`, any other case state is `ERR_INVALID_STATE`, and the batch must be `EXECUTED` or `RECON_EXCEPTION`. The new IRA's `ira_origin` records how it came to be — `ELECTED` or `AUTO_FORCE_OUT` — and it is funded with the case's full `vested_balance_cents`: `funded_amount_cents` is that balance, and `balance_cents` starts equal to it. The request may select a `fee_day_count_convention` of `ACTUAL_365` or `THIRTY_360`, defaulting to `ACTUAL_365`. Every IRA is invested in `MONEY_MARKET_FDIC_INSURED`, a principal-preservation `default_investment` that never changes. At establishment, `opened_at` and `last_activity_at` are stamped; `in_flight_cents`, `total_fees_cents`, and `total_transferred_out_cents` start at zero; `last_fee_assessed_at` stays null until the first assessment. Establishment settles the case — `SETTLED` with `executed_path` `SAFE_HARBOR_IRA` — executes the election if one exists, recomputes the batch totals, and increments the case's `version`; the case's `participant_id` is copied onto the IRA.

The IRA's `balance_cents` is always explainable: it equals `funded_amount_cents` minus `total_fees_cents`, minus `total_transferred_out_cents`, minus `in_flight_cents`, and is maintained on every money event.

Maintenance fees are assessed periodically by `ProviderOps` against an IRA that is `OPEN` or `MATCHED` — any other status is `ERR_INVALID_STATE`. Assessment is gated on disclosure: unless a `FEE_DISCLOSURE` notice for the case has reached `DELIVERED`, the assessment is rejected with `ERR_FEE_DISCLOSURE_NOT_DELIVERED`. The annual maintenance fee is 6,000 cents — sixty dollars — prorated over the accrual period. The period runs from an anchor, exclusive, through the current instant, inclusive; the anchor is `last_fee_assessed_at` once any assessment exists and `opened_at` before the first. Under `ACTUAL_365`, `days_in_period` is the count of calendar days in the period and the fee is 6,000 cents times the day count divided by 365. Under `THIRTY_360` the count is banker's style — thirty times the ending month number minus the starting month number, plus the ending day-of-month capped at thirty, minus the starting day-of-month capped at thirty, plus three hundred sixty times the ending year minus the starting year — and the fee is 6,000 cents times that count divided by 360. Either way the fee is rounded half-up to integer cents: an August-1-to-September-1 period bills 510 cents under `ACTUAL_365` (thirty-one days) and 500 cents under `THIRTY_360` (thirty days). The posted `amount_cents` is the lesser of the computed fee and the IRA's `balance_cents` at assessment, so a fee never drives the balance below zero. Only one assessment may post per IRA per UTC calendar month, measured by `period_end`; a second attempt in the same month is rejected with `ERR_DUPLICATE_FEE_PERIOD`.

Each assessment appends a row to the append-only fee ledger carrying the `safe_harbor_ira_id`, the `period_start` (the anchor), the `period_end` (the assessment instant), the `days_in_period`, the `day_count_convention` copied from the IRA, and the `amount_cents`; in the same stroke the IRA's `balance_cents` drops by the amount, `total_fees_cents` rises by the same, `last_fee_assessed_at` advances to the period end, `last_activity_at` refreshes, and the IRA's `version` increments.

A participant who wants out — or `ProviderOps` acting for them — may close an IRA that is `OPEN` or `MATCHED`; a `Participant` caller must own the IRA, otherwise `ERR_PARTICIPANT_OWNERSHIP_MISMATCH`. Closure pays the entire remaining `balance_cents` by check: a check with `origin` `IRA_CLOSE` is created for the full balance with no withholding at all — both withholding components are zero and the payable equals the gross — and the balance falls to zero through the in-flight check linkage. If the IRA was `MATCHED`, its confirmed match expires to `EXPIRED`. The IRA lands in `CLOSED_BY_PARTICIPANT` and its `version` increments.

### 3.7. Auto-Portability Matching and Plan-to-Plan Transfers

While an IRA is `OPEN`, `ProviderOps` may probe the network for the participant's new-employer plan — provided the plan that originally forced the money out still has `auto_portability_enabled` true. Each probe supplies `new_plan_id`, `new_recordkeeper_id`, the `employment_start_date` (in `YYYY-MM-DD` form) from the network feed, and three feed signals: `ssn_exact`, `name_similarity` (a feed score from 0 to 1 with two-decimal granularity), and `dob_match`. Referential integrity is checked before scoring: the new plan's recordkeeper must equal `new_recordkeeper_id` (`ERR_RECORDKEEPER_PLAN_MISMATCH`), that recordkeeper must be `ACTIVE` (`ERR_RECORDKEEPER_NOT_ACTIVE`), and the new plan must be `network_reachable` (`ERR_DESTINATION_PLAN_NOT_ACCEPTING`). Each probe creates exactly one match candidate, with `participant_id` copied from the IRA.

Scoring is weighted. The `match_score` adds three contributions — 0.55 when `ssn_exact` is true, thirty percent of `name_similarity`, and 0.15 when `dob_match` is true — and rounds the sum half-up to three decimal places. Banding then decides the candidate's disposition. A score below 0.400 creates the candidate already `REJECTED`. A score of at least 0.400 but below 0.850 parks the candidate in `CANDIDATE`, the manual-review queue — a score of exactly 0.400 lands here. A score of at least 0.850 confirms immediately, but only when `ssn_exact` is true; the same score without an exact SSN falls back to `CANDIDATE`, because the SSN gate caps non-SSN feeds at 0.45 and they can never auto-confirm. A score of exactly 0.850 with an exact SSN confirms on the spot. Confirmation — automatic or manual — flips the IRA from `OPEN` to `MATCHED` and expires every other `CANDIDATE` of the same IRA to `EXPIRED`, keeping at most one `CONFIRMED` match per IRA at any time.

Manual review can confirm or reject a `CANDIDATE`. A manual confirm checks the SSN gate first — a candidate without an exact SSN is rejected with `ERR_SSN_GATE_FAILED` — and only then the score floor: a `match_score` below 0.650 is rejected with `ERR_MATCH_SCORE_BELOW_THRESHOLD`, so a candidate sitting between 0.400 and 0.650 can be reviewed but never confirmed. Rejection simply moves the candidate to `REJECTED`. Either action increments the candidate's `version`. Candidates also expire without review: the sweep (§3.8) expires any `CANDIDATE` older than ninety days, and the recordkeeper-exit cascade (§2.8) expires candidates whose destination plan went dark.

With a unique `CONFIRMED` match in hand and the IRA `MATCHED`, `ProviderOps` initiates the plan-to-plan transfer, optionally naming `match_candidate_id` — it defaults to the IRA's unique confirmed match. The request must carry `expected_ira_version` equal to the IRA's current `version`, and a stale view is rejected with `ERR_STALE_VERSION` (412). Two prenotice gates then apply: an `AUTO_PORTABILITY_PRENOTICE` notice for the case must have reached `DELIVERED` (`ERR_PRENOTICE_NOT_DELIVERED`), and its opt-out window must already have closed — the prenotice's `response_deadline` must be before the current instant, otherwise `ERR_PRENOTICE_WINDOW_OPEN`. The match's recordkeeper must still be `ACTIVE` (`ERR_RECORDKEEPER_NOT_ACTIVE`). Finally, the transferable amount is computed in a pinned order, because the accrual depends on the balance and the amount depends on the accrual: first, snapshot the IRA's `balance_cents`, already net of every posted fee; second, compute the accrued-but-unbilled maintenance fee from the fee anchor — `last_fee_assessed_at`, or `opened_at` when never assessed — to the current instant under the IRA's day-count convention, but without the balance cap that a posted assessment would apply; third, subtract the accrual from the snapshot. The difference becomes the transfer's `amount_cents`, and the withheld accrual is recorded as `accrued_fee_offset_cents`, retained by the provider rather than transferred. If the difference is not positive, initiation is rejected with `ERR_INSUFFICIENT_IRA_BALANCE`.

Initiation creates the transfer `SENT` with `sent_at` stamped, moves the match from `CONFIRMED` to `EXECUTED`, and moves the IRA from `MATCHED` to `TRANSFER_PENDING`: `balance_cents` drops by the amount, `in_flight_cents` rises by the same, `last_activity_at` refreshes, and the IRA's `version` increments.

The receiving recordkeeper's answer is recorded with an `outcome` of `ACCEPTED` or `REJECTED` — any other value is `ERR_INVALID_REQUEST` — and `REJECTED` requires a non-empty `rejection_reason`. Acceptance reconciles everything: the transfer moves to `RECONCILED` with `settled_at` stamped, the IRA's `in_flight_cents` drops by the amount while `total_transferred_out_cents` rises by the same, `last_activity_at` refreshes, the IRA settles in `TRANSFERRED_OUT`, and the transfer's `version` increments. Rejection unwinds in three links: the transfer becomes `RETURNED` with `settled_at` stamped; the IRA is re-credited — `in_flight_cents` down by the amount, `balance_cents` up by the same — and returns from `TRANSFER_PENDING` to `OPEN` with `last_activity_at` refreshed, reopening it for a fresh match search; and the match falls from `EXECUTED` to `REJECTED`.

### 3.8. Unclaimed Property: Stale Checks, Reissue, and Escheatment

Checks do not live forever. A check is stale once the current instant passes its `stale_after` — the boundary is exclusive for the holder: recording the check as cashed at exactly `stale_after` still succeeds, and one instant later it fails with `ERR_CHECK_STALE`. Recording a cash is a `ProviderOps` action on an `ISSUED` check: it moves `check_status` from `ISSUED` to `CASHED`, stamps `cashed_at`, increments the check's `version`, and — for a check of `origin` `CASE_CASH_OUT` — settles the underlying case from `EXECUTED` to `SETTLED` and recomputes the batch's `settled_case_count`. The sweep, meanwhile, moves every `ISSUED` check whose `stale_after` has passed into `STALE_DATED`.

A check that is `ISSUED` or `STALE_DATED` may be voided with a `void_reason` of `DAMAGED`, `STALE`, or `ESCHEATMENT` — any other reason is `ERR_INVALID_REQUEST`. Voiding stamps `voided_at` and increments the check's `version`. Escheatment is the heavy path: it is permitted only on a `STALE_DATED` check, and only when an `ESCHEAT_WARNING` notice for the case was delivered at least ninety days earlier — otherwise the void is rejected with `ERR_ESCHEAT_WARNING_REQUIRED`. An escheatment void of a `CASE_CASH_OUT` check cascades in three links: the check goes `VOIDED`; the case moves from `EXECUTED` to `ESCHEATED`; and the batch's `settled_case_count` and `total_forced_out_cents` are recomputed, which can flip the batch's reconciliation eligibility (§3.9).

A `VOIDED` check can be reissued — unless it was voided for escheatment, which is final. Reissue requires the underlying case still `EXECUTED` — not `ESCHEATED` or `CANCELLED`, otherwise `ERR_INVALID_STATE` — and a deliverable address: a participant whose `address_quality` is `BAD_ADDRESS` blocks reissue with `ERR_UNDELIVERABLE_ADDRESS`, while `UNVERIFIED` remains acceptable. The reissue spawns a successor check, `ISSUED` fresh, with its `supersedes_check_id` pointing at the predecessor — that field is null on a first issue — carrying identical amount fields and a fresh `issued_at` and `stale_after`; the predecessor row stays `VOIDED`, so the chain of custody is preserved end to end.

IRAs escheat too, through dormancy rather than paper. When the sweep finds an `OPEN` IRA whose `last_activity_at` is more than 1,095 days — three years — in the past (exactly 1,095 days is not yet dormant), and an `ESCHEAT_WARNING` for the case was delivered at least ninety days earlier, the IRA moves to `ESCHEATED` and its remaining `balance_cents` escheats to the state, leaving the balance at zero.

The sweep is the single deterministic time-keeping pass, run by `ProviderOps`: it expires open election windows whose deadline has passed (a `NOTIFIED` case with no `SUBMITTED` election moves to `WINDOW_EXPIRED`), stales checks past `stale_after`, expires `CANDIDATE` matches older than ninety days, and escheats dormant `OPEN` IRAs whose warning has matured. It reports how much it did through four counters: `cases_window_expired`, `checks_staled`, `matches_expired`, and `iras_escheated`. Nothing in the system transitions on the clock alone — only on a sweep.

### 3.9. Batch Reconciliation and Fiduciary Review

Execution does not close a batch; reconciliation does. `ProviderOps` reconciles a batch standing in `EXECUTED`: if every attached case has reached a terminal status — `SETTLED`, `ESCHEATED`, or `CANCELLED` — the batch moves to `RECONCILED` and stamps `reconciled_at`; if at least one case is still `EXECUTED`, an uncashed check outstanding, the batch instead moves to `RECON_EXCEPTION`, touching no cases and recording that money movement is unsettled. Either way the reconciliation counters are recomputed and the batch's `version` increments. From `RECON_EXCEPTION`, resuming after remediation returns the batch to `EXECUTED` and recomputes the counters again, also incrementing `version`.

The counters are defined precisely, over the cases of this batch only: `case_count` counts every case attached to the batch; `settled_case_count` counts those in exactly `SETTLED`, `ESCHEATED`, or `CANCELLED`; and `total_forced_out_cents` sums `vested_balance_cents` over the cases whose `executed_path` is one of `CHECK_CASH_OUT`, `SAFE_HARBOR_IRA`, or `DIRECT_NEW_PLAN`. A batch is reconciliation-eligible exactly when `case_count` equals `settled_case_count` and at least one case exists.

Every reconciled batch then faces independent fiduciary review. A `FiduciaryReviewer` opens a review by naming the `distribution_batch_id` and a coverage window — `period_start` inclusive, `period_end` exclusive. The batch must be `RECONCILED`, otherwise `ERR_INVALID_STATE`; segregation of duties forbids the reviewer from being the operator who executed the batch — the reviewer's `X-User-ID` is compared to the batch's `executed_by_user_id` and equality is rejected with `ERR_SEGREGATION_OF_DUTIES`; the window must be non-empty — `period_start` before `period_end`, otherwise `ERR_REVIEW_PERIOD_INVALID`; and the window must not intersect any existing non-`CLOSED` review of the same plan under half-open semantics — one review's `period_end` equal to another's `period_start` is adjacency, not overlap, and is allowed, while a true intersection is rejected with `ERR_REVIEW_PERIOD_OVERLAP`. The new review copies `plan_id` from the batch, records the caller as `reviewer_user_id`, and opens in `OPEN` with `findings_count` zero and `attested_at` null.

The review lifecycle belongs to the named reviewer alone: every review action requires `X-User-ID` to equal the review's `reviewer_user_id`. Recording a finding moves the review from `OPEN` to `REMEDIATION_OPEN` and adds one to `findings_count`; recording further findings while `REMEDIATION_OPEN` keeps the status and keeps incrementing the count. Verifying remediation moves the review back to `OPEN`, with the findings remaining counted for the record. Attestation is permitted only from `OPEN` — no unremediated findings — and stamps `attested_at`, closes the review (`CLOSED`), and in the same stroke moves the reviewed batch from `RECONCILED` to `REVIEWED`, its terminal state. Each review action increments the review's `version`.

## 4. Endpoint Definitions

Operations that create a new resource — a recordkeeper, plan, participant, batch, case, notice, election, IRA, fee assessment, check, reissued successor check, match candidate, transfer, or fiduciary review — return `201 Created`. Operations that act on an existing resource — status actions, configuration updates, delivery recordings, voids, closes, confirmations, responses, sweeps, and the clock — return `200 OK`. Request and response shapes for each operation are governed by the narratives of §2 and §3; the table below is an index of the HTTP contract only. All retrieval endpoints (list and detail) are readable by every declared role and are marked "All roles".

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/recordkeepers` | Register a recordkeeper in the network | ProviderOps |
| GET | `/recordkeepers` | List recordkeepers (filter: `network_status`) | All roles |
| GET | `/recordkeepers/{id}` | Get one recordkeeper | All roles |
| POST | `/recordkeepers/{id}/activate` | Activate from PENDING_ONBOARD or reinstate from SUSPENDED | ProviderOps |
| POST | `/recordkeepers/{id}/suspend` | Suspend network participation | ProviderOps |
| POST | `/recordkeepers/{id}/exit` | Exit the network (terminal; cascades to plans, matches, IRAs) | ProviderOps |
| POST | `/plans` | Register an employer plan | PlanSponsor |
| GET | `/plans` | List plans (filters: `recordkeeper_id`, `plan_status`) | All roles |
| GET | `/plans/{id}` | Get one plan | All roles |
| PATCH | `/plans/{id}` | Update force-out configuration (OCC-guarded) | PlanSponsor |
| POST | `/plans/{id}/terminate` | Terminate the plan (blocked while a batch is in flight) | PlanSponsor |
| POST | `/participants` | Register a separated participant (census feed) | PlanSponsor, ProviderOps |
| GET | `/participants` | List participants (filters: `ssn_hash`, `address_quality`) | All roles |
| GET | `/participants/{id}` | Get one participant | All roles |
| PATCH | `/participants/{id}` | Update mailing address (marks address VALID); Participant may only update self | PlanSponsor, ProviderOps, Participant |
| POST | `/distribution-batches` | Open a force-out batch for a plan (one in-flight batch per plan) | PlanSponsor |
| GET | `/distribution-batches` | List batches (filters: `plan_id`, `batch_status`) | All roles |
| GET | `/distribution-batches/{id}` | Get one batch (with computed counters) | All roles |
| POST | `/distribution-batches/{id}/lock` | Lock the batch; run valuation and force-out path determination per case | PlanSponsor |
| POST | `/distribution-batches/{id}/execute` | Execute the locked batch (records the executing operator) | ProviderOps |
| POST | `/distribution-batches/{id}/reconcile` | Reconcile: all cases terminal becomes RECONCILED; otherwise RECON_EXCEPTION | ProviderOps |
| POST | `/distribution-batches/{id}/resume` | Resume from RECON_EXCEPTION after remediation | ProviderOps |
| POST | `/distribution-cases` | Attach a separated participant's case to an OPEN batch | PlanSponsor |
| GET | `/distribution-cases` | List cases (filters: `distribution_batch_id`, `plan_id`, `participant_id`, `case_status`) | All roles |
| GET | `/distribution-cases/{id}` | Get one case | All roles |
| POST | `/distribution-cases/{id}/cancel` | Cancel a case (rehire / census error) while IDENTIFIED or NOTIFIED | PlanSponsor |
| POST | `/distribution-cases/{id}/settle-direct-rollover` | Execute an ELECTED DIRECT_ROLLOVER_NEW_PLAN case (plan-to-plan, no IRA) | ProviderOps |
| POST | `/distribution-cases/{id}/notices` | Send a notice to the case's participant | ProviderOps |
| GET | `/notices` | List notices (filters: `distribution_case_id`, `notice_type`, `delivery_status`) | All roles |
| GET | `/notices/{id}` | Get one notice | All roles |
| POST | `/notices/{id}/record-delivery` | Record a mail-tracking outcome | ProviderOps |
| POST | `/distribution-cases/{id}/elections` | Participant submits (or supersedes) an election within the notice window (OCC-guarded) | Participant |
| GET | `/elections` | List elections (filters: `distribution_case_id`, `participant_id`, `destination_plan_id`, `election_status`) | All roles |
| GET | `/elections/{id}` | Get one election | All roles |
| POST | `/elections/{id}/void` | Participant revokes a SUBMITTED election while the window is open | Participant |
| POST | `/safe-harbor-iras` | Establish a safe harbor IRA for an ELECTED (SAFE_HARBOR_IRA) or WINDOW_EXPIRED (IRA path) case | ProviderOps |
| GET | `/safe-harbor-iras` | List IRAs (filters: `distribution_case_id`, `participant_id`, `ira_status`) | All roles |
| GET | `/safe-harbor-iras/{id}` | Get one IRA | All roles |
| POST | `/safe-harbor-iras/{id}/close` | Participant opt-out / provider close: pays the remaining balance by check | Participant, ProviderOps |
| POST | `/safe-harbor-iras/{id}/assess-fee` | Assess the periodic maintenance fee for the elapsed accrual period | ProviderOps |
| GET | `/fee-assessments` | List fee ledger entries (filter: `safe_harbor_ira_id`) | All roles |
| GET | `/fee-assessments/{id}` | Get one fee ledger entry | All roles |
| POST | `/checks` | Issue the cash-out check for an ELECTED (LUMP_SUM_CASH) or WINDOW_EXPIRED (CASH_OUT) case | ProviderOps |
| GET | `/checks` | List checks (filters: `distribution_case_id`, `check_status`, `supersedes_check_id`, `origin`) | All roles |
| GET | `/checks/{id}` | Get one check | All roles |
| POST | `/checks/{id}/record-cashed` | Record bank confirmation that the check cleared | ProviderOps |
| POST | `/checks/{id}/void` | Void an ISSUED or STALE_DATED check; ESCHEATMENT settles the case to the state | ProviderOps |
| POST | `/checks/{id}/reissue` | Reissue a VOIDED (non-escheatment) check as a linked successor | ProviderOps |
| POST | `/safe-harbor-iras/{id}/match-searches` | Run one network match probe for an OPEN IRA; creates a scored match candidate | ProviderOps |
| GET | `/match-candidates` | List match candidates (filters: `safe_harbor_ira_id`, `participant_id`, `new_plan_id`, `new_recordkeeper_id`, `match_status`) | All roles |
| GET | `/match-candidates/{id}` | Get one match candidate | All roles |
| POST | `/match-candidates/{id}/confirm` | Manually confirm a CANDIDATE-band match | ProviderOps |
| POST | `/match-candidates/{id}/reject` | Reject a CANDIDATE-band match | ProviderOps |
| POST | `/safe-harbor-iras/{id}/transfers` | Initiate the auto-portability transfer of a MATCHED IRA to the new employer plan | ProviderOps |
| GET | `/transfers` | List transfers (filters: `safe_harbor_ira_id`, `match_candidate_id`, `transfer_status`) | All roles |
| GET | `/transfers/{id}` | Get one transfer | All roles |
| POST | `/transfers/{id}/record-response` | Record the receiving recordkeeper's acceptance or rejection | ProviderOps |
| POST | `/fiduciary-reviews` | Open a fiduciary review of a RECONCILED batch (segregation of duties enforced) | FiduciaryReviewer |
| GET | `/fiduciary-reviews` | List reviews (filters: `distribution_batch_id`, `plan_id`, `review_status`) | All roles |
| GET | `/fiduciary-reviews/{id}` | Get one review | All roles |
| POST | `/fiduciary-reviews/{id}/record-finding` | Record a finding (moves the review to REMEDIATION_OPEN) | FiduciaryReviewer |
| POST | `/fiduciary-reviews/{id}/verify-remediation` | Accept remediation of all findings (back to OPEN) | FiduciaryReviewer |
| POST | `/fiduciary-reviews/{id}/attest` | Attest the process (only from OPEN); closes the review and marks the batch REVIEWED | FiduciaryReviewer |
| POST | `/sweeps/run` | Run the deterministic clock-driven sweep (windows, staleness, match aging, dormancy escheat) | ProviderOps |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving; no entity mutations) | ProviderOps |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The trigger conditions for each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_PARTICIPANT_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_FEE_DISCLOSURE_NOT_DELIVERED` | 422 Unprocessable Entity |
| `ERR_PRENOTICE_NOT_DELIVERED` | 422 Unprocessable Entity |
| `ERR_ESCHEAT_WARNING_REQUIRED` | 422 Unprocessable Entity |
| `ERR_CASE_NOTICE_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_ELECTION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_PRENOTICE_WINDOW_OPEN` | 422 Unprocessable Entity |
| `ERR_CHECK_STALE` | 422 Unprocessable Entity |
| `ERR_CASE_WINDOW_STILL_OPEN` | 422 Unprocessable Entity |
| `ERR_REVIEW_PERIOD_INVALID` | 422 Unprocessable Entity |
| `ERR_PLAN_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_RECORDKEEPER_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_RECORDKEEPER_PLAN_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DESTINATION_PLAN_NOT_ACCEPTING` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_OPEN_BATCH` | 409 Conflict |
| `ERR_DUPLICATE_FEE_PERIOD` | 409 Conflict |
| `ERR_REVIEW_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_THRESHOLD_CONFIG_INVALID` | 422 Unprocessable Entity |
| `ERR_CASE_BALANCE_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_IRA_BALANCE` | 422 Unprocessable Entity |
| `ERR_MATCH_SCORE_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_SSN_GATE_FAILED` | 422 Unprocessable Entity |
| `ERR_UNDELIVERABLE_ADDRESS` | 422 Unprocessable Entity |
