# Worklog — task_1339_card_dispute_regulation_e_chargeback

## Step 1: Create Task Directory — 2026-08-12T22:38:44.000Z

Task directory `tasks/task_1339_card_dispute_regulation_e_chargeback/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-12T23:12:48.000Z

Scaffold generation complete. Lint verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1339_card_dispute_regulation_e_chargeback/SCAFFOLD.yaml` — §1.0–§1.7 (response envelope verbatim; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1339_card_dispute_regulation_e_chargeback/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1339_card_dispute_regulation_e_chargeback/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

## Counts

- Entities: 8 (CardAccount, CardTransaction, DisputeCase, ProvisionalCredit, Chargeback, Representment, Notification, LossRecovery)
- Endpoints: 28 (including `POST /_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default, and filtered-list/sub-resource GETs covering every FK)
- Errors: 18
- Calculations: 6; State machines: 6; Roles: 6 (Cardholder entity_backed:CardAccount; IntakeAgent/DisputeInvestigator/ChargebackAnalyst/FinanceOfficer/BankAdmin opaque)
- Difficulty instances: 18 (2 per rule, all 9 rules); Corner instances: 28 active + 2 excluded stubs

## Notable design decisions

- **Archetype**: compliance/audit primary + workflow orchestration; flat topology; cyclic state machines; segregation-of-duties role model (resolver's X-User-ID must differ from `intake_agent_id` → `ERR_SOD_VIOLATION`).
- **Reg E mechanics encoded**: provisional credit due at 10 business days (20 for new accounts ≤30 days), business-day counting pinned (Mon–Fri, day after receipt); investigation window 45/90 days keyed on {fraud flag, POS_PIN/POS_SIGNATURE, account age} — the combinatorial mode-(a) instance; tiered consumer liability ($50 ≤2 days / $500 ≤60 days / full after) with provisional (claimed delay) vs final (verified delay) variants — Rule 1 instance on DisputeCase.
- **Chargeback economics**: per-stage fee rounding pinned (round half-up per stage, then sum) — mode-(b) instance; PRE_COMPLIANCE vs ARBITRATION fee variants — Rule 1 second instance on Chargeback domain. Verified literals: 12660 vs 27800 on 20000; 12767 on 33333.
- **Cycles for Rule 3**: DisputeCase CHARGEBACK_FILED ⇄ REPRESENTMENT_REVIEW (second presentment) and ProvisionalCredit GRANTED → REVERSED → REINSTATED correction loop.
- **Cascades for Rule 4**: depth-3 chain from credit reversal (credit → case → account restore + letter) and depth-2 from representment accept (chargeback → case → auto loss entry + notice).
- **Temporal overlap (Rule 8)**: point-occupancy duplicate-dispute rule vs half-open `[filed_at, filed_at+30d)` chargeback response-window occupancy (survives CANCELLED; refile at exactly the window end +1s permitted — boundary asserted).
- **OCC (§1.2.1)**: single true race — `POST /disputes/{id}/reclassify` guarded by `expected_dispute_version` (412 `ERR_STALE_VERSION`); all other conflicts reduced to state preconditions.
- **Logical clock drives every deadline**; all date/fees literals in test recipes were verified by executing the formulas in Python before pinning.
- No sibling task directories were inspected; the design was derived solely from the scenario text and the skill specification.

## Step 3: Copy Shared Files — 2026-08-12T23:12:48.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1339_card_dispute_regulation_e_chargeback/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T23:21:39.000Z

PRD generation complete.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1339_card_dispute_regulation_e_chargeback/workspace/PRD.md` — 238 lines, 5 top-level sections (Introduction; Global Specifications §2.1–§2.10; Business Logic §3.1–§3.8; Endpoint Definitions; Error Code Catalogue).

**Structure:**
- §2 (10 subsections): RBAC with per-role identity translation (Cardholder entity-backed by CardAccount; the five staff roles opaque), verbatim §2.2 response envelope, pagination (limit 10/min 1/max 100, offset 0, `created_at` ascending), logical clock + deadline conventions (startup default `2026-08-01T00:00:00Z`, Mon–Fri business days counted from the day after, 23:59:59Z inclusive deadlines), common resource properties (Notification/LossRecovery explicitly carry only `id`/`created_at`), integer-cent precision with pinned per-stage round-half-up fee rounding, OCC on reclassification only, the 11-tier validation priority ladder, fraud restriction cascade, and segregation of duties.
- §3 (8 subsections, chronological workflow): account/transaction seeding → intake + provisional credit clock → classification/liability tiers/investigation window (90 vs 45 days) → credit grant + both resolution outcomes → chargeback filing (VISA 120 / MC 90 day deadlines, 30-day half-open response window, reason-code/fraud matrix) → representment/second presentment/escalation (filing fee 2,500c; pre-compliance 10,000c + 0.8%; arbitration 25,000c + 1.5%) → reversal (3-business-day notice cooling), reinstatement, withdrawal → loss/recovery ledger.
- §4: 27-endpoint table, 4 columns only. §5: all 18 error IDs, 2 columns only.

**Contract verification (mechanical, all PASS):**
- Contract 1 field coverage: 60 required identifiers (entity fields, endpoint inputs, query params, OCC field, `doc_type`/`reference`, `current_utc`, common fields) — 0 missing after adding `chargeback_id` to §3.6.
- Contract 2 rule coverage: all state-machine transitions, both OCC rule elements (`expected_dispute_version` → `ERR_STALE_VERSION`/412), all 6 calculations (liability tiers, credit amount, investigation window, credit deadline, network fees with pinned rounding, recovery waterfall incl. claim conservation), all validation conditions paired with error IDs in prose, all endpoint side effects and cascades (including the CANCELLED-chargeback retained filing fee, withdrawal waiving notice cooling, refile path) expressed.
- Contract 3 §3 path purity: 327 backtick tokens scanned, 0 path/method violations.
- All state enum values, role names, and the 18 error IDs verified present verbatim.

**Design-index isolation confirmed:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; the PRD was generated solely from `SKILL.md`, `section-2.2-response-structure.md`, `example-prd.md`, and `SCAFFOLD.yaml`.

## Step 5: Generate Unit Tests — 2026-08-12T23:38:41.000Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1339_card_dispute_regulation_e_chargeback/test_helpers/`):
- `types.py` — status enums + TypedDicts; `Notification`/`LossRecovery` correctly carry only `id` + `created_at` (no `updated_at`/`version` per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with 25 endpoint methods covering every PRD §4 row including `/_clock/set_current_utc`
- `api_errors.py` — all 18 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_claim_conservation` / ledger invariants
- `factories.py`, `constants.py` (liability tiers, fee constants, precomputed business-day deadlines), `test_users.py` (shared constants + `make_cardholder_headers(account_id)` for the entity-backed Cardholder role), `fixtures.py` (5 tiers incl. `setup_reversal_pending`, `setup_second_presented`, `setup_representment_accepted_case`, `setup_resolved_merchant_favor_via_reversal`), `__init__.py` barrel

**`test_suite/`**: `conftest.py` + 9 test files (`test_01_accounts_and_intake` … `test_09_concurrency_and_read_models`).

## Test counts
- **Queue A (Difficulty): 18/18 instances, each with ≥2 tests** (38 tests)
- **Queue B (Corner): 28/28 non-stub instances, each with ≥1 test** (32 tests); both `excluded_because:` stubs verified to resolve to real difficulty instances and not translated
- **70 tests total**, all collected by pytest cleanly

## Skipped instances
None. Every instance passed the PRD-first two-condition filter — the PRD's §2.8 priority ladder, §2.7 OCC, and §3.x workflow prose verbatim-cover all asserted rules with unique derivability.

## Coverage audit results
- Zero shortfalls on both queues; zero orphan `Design:` tags; zero untagged/dual-tagged test functions (all 70 docstrings end with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line copied verbatim from the YAMLs)
- Verbatim-citation sweep: an automated grep of every quoted docstring sentence against `PRD.md` passes with **zero misses** (initial 9 misses from ellipsized quotes were fixed by splitting/quoting full sentences)
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no freelance scaffold-walked tests (no baseline CRUD, pagination, or RBAC tests beyond what the two indices enumerate)

## Step 6: Generate Implementation — 2026-08-12T23:38:41.000Z

Done. The implementation is complete and verified end-to-end.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1339_card_dispute_regulation_e_chargeback/workspace/implementation/`)

- `start.sh` — foreground launcher, guards `pip install` behind `python3 -c "import flask"`, `exec python3 app.py`, honors `PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask entry, error handlers (envelope-shaped 404/405/exception), `POST /_clock/set_current_utc`, blueprint registration
- `state.py` — logical-clock singleton (boots at exactly `2026-08-01T00:00:00Z`, never wall-clock)
- `clock.py` — ISO-8601 parsing/formatting, end-of-day 23:59:59Z, business-day add/count (Mon–Fri, counting from day after)
- `db.py` — in-memory dict stores keyed by id, creation-sequence counter; starts fully empty, zero seeding
- `errors.py` — `ApiError` + all 18 scaffold error IDs with exact HTTP statuses
- `response.py` — envelope per §1.0: `meta.api_request_id` (`req_…`), `meta.api_request_timestamp` (3-fractional-digit ISO), `response_type`, `data`; pagination fields `limit/offset/total_count/has_more` in `meta` for lists
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (6 roles), role gating, Cardholder ownership
- `helpers.py` — body-schema validation (unknown-field rejection, positive-integer amounts), pagination (default 10, min 1, max 100), liability-tier engine, investigation-window/provisional-deadline/network-deadline math, Decimal ROUND_HALF_UP stage fees, cascade helpers
- `routes_accounts.py`, `routes_disputes.py`, `routes_chargebacks.py` — all 25 endpoints

## Endpoints implemented (25/25)

`POST/GET /card-accounts`, `GET /card-accounts/{id}/transactions`, `POST /card-transactions`, `POST/GET /disputes` (+list filters), `POST /disputes/{id}/classify|reclassify|grant-provisional-credit|resolve|withdraw`, `POST/GET /chargebacks` (+list), `GET /disputes/{id}/chargebacks|provisional-credits|notifications|loss-recoveries`, `POST /chargebacks/{id}/representments|review-representment|escalate|withdraw`, `GET /chargebacks/{id}/representments`, `POST /provisional-credits/{id}/reverse|reinstate`, `POST /disputes/{id}/loss-recoveries`, `POST /_clock/set_current_utc`.

## Verification performed

Booted via `start.sh` on fresh processes and smoke-tested: full intake→classify→grant→resolve (ERROR_CONFIRMED true-up +5000), NO_ERROR→REVERSAL_PENDING→3-business-day cooling→reverse→reinstate loop, chargeback file→represent→REJECT→escalate WON/LOST at both stages (fee math verified: 2500+25450=27950 arbitration, 2500+10099=12599 pre-compliance), withdraw/refile, OCC 412, SoD 403, ERR_PROVISIONAL_CREDIT_REQUIRED precedence over window-expiry, network deadline 422, duplicate-dispute 409, account RESTRICTED cascades (block seeding, restore on reclassify/resolution), `granted_late`, loss-ledger bound `ERR_LOSS_EXCEEDS_OUTSTANDING`, cardholder ownership scoping on GETs/lists, and pagination meta.

## Interpretation decisions where the PRD left choices open

1. **Direct-FINALIZED credit fields** (resolve ERROR_CONFIRMED with no prior grant): set `amount_cents = final_amount_cents = F`, `granted_at = now`, `granted_late = False` (the "granted after due date" comparison is meaningless for a resolution-time creation).
2. **Response-window occupancy**: only non-terminal chargebacks (`FILED`, `REPRESENTED`, `SECOND_PRESENTED`) occupy `[filed_at, response_window_end_at)`; `CANCELLED`/`WITHDRAWN`/`CLOSED_*` free the window immediately (this is what enables the documented refile path).
3. **REVERSED credits count as "ever granted"** for the ERR_PROVISIONAL_CREDIT_REQUIRED gate, since a record only exists after a grant.
4. **`initial_balance_cents` and `claimed/verified_report_delay_days`** validated as integers ≥ 0 (scaffold declares an explicit `default: 0` and "calendar days"); all other monetary amounts must be > 0.
5. **Cardholder list scoping**: `GET /disputes` silently restricts to own cases; passing a `card_account_id` filter for someone else's account returns `ERR_FORBIDDEN` (ownership tier).
6. **`stage_entered` initializes to `"NONE"`**, `outcome` to null, and unused computed case fields (`investigation_window_days`, `final_liability_cents`, etc.) to null until their computation event.
7. **List sort stability**: a monotonic creation sequence breaks ties, since the logical clock can sit still across multiple creations.
8. **LOSS_RECOGNIZED auto-entries with a zero total are skipped** ("created only when > 0"); RECOVERY_RECEIVED at CLOSED_WON is always booked (amount_cents > 0 by construction).

## Step 7: Test-and-fix iteration loop (2026-08-12)

- Baseline probe: 68/70; 8-round sweep surfaced 2 deterministic failures + 9 infra flakes ("could not be restarted" / mid-test connection resets under host load).
- Fix 1 (implementation, `routes_chargebacks.py` filing occupancy): removed the status skip for CANCELLED/WITHDRAWN/CLOSED_* chargebacks — PRD §3.6 states a fresh filing is "permitted once the cancelled chargeback's response window no longer occupies the timeline", so occupancy is purely interval-based `[filed_at, response_window_end_at)`. Worklog interpretation decision #2 was wrong.
- Fix 2 (test bug, `test_suite/test_09_concurrency_and_read_models.py`): added missing `set_clock` import (NameError).
- Fix 3 (infrastructure, `start.sh`): replaced per-boot `python3 -c "import flask"` guard (~0.7s of the ~2s boot × 560 restarts/sweep) with a `.deps_ok` stamp file, cutting boot to ~0.6s against the runner's 15s restart poll.
- Result: 2 consecutive 8-round parallel sweeps, all rounds 70/70 (16/16 clean). No tests deleted.

## Step 7: Run Tests and Iterate — 2026-08-12T23:54:20.000Z

All done. Final state: two consecutive 8-round parallel sweeps, every round 70/70 (16/16 clean rounds).

## Summary

**Iterations run:** 3 sweeps total — (1) initial sweep: timed out at 10 min under host load, no results; (2) single-round probe (68/70) + first full 8-round sweep (66–69/70 per round, mixed deterministic + infra failures); (3) post-fix 8-round sweep 70/70 ×8, plus a confirmation 8-round sweep 70/70 ×8.

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1339_card_dispute_regulation_e_chargeback/test_suite/test_09_concurrency_and_read_models.py` — `test_list_disputes_filtered_by_status_paginated` used `set_clock` without importing it (NameError); added `set_clock` to the `test_helpers` import list. Pure test bug; the asserted PRD rules (§3.8 status filter, §2.3 pagination meta) were already correctly implemented.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1339_card_dispute_regulation_e_chargeback/workspace/implementation/routes_chargebacks.py` (chargeback filing, window-occupancy gate): the code skipped `CANCELLED`/`WITHDRAWN`/`CLOSED_*` chargebacks when checking response-window occupancy, so a refile 10 days after a withdrawal succeeded. PRD §3.6 verbatim: "The case is then eligible for a fresh filing — permitted once the cancelled chargeback's response window no longer occupies the timeline" — i.e., a cancelled chargeback's window keeps occupying `[filed_at, response_window_end_at)` until it expires. Removed the status skip; occupancy is now purely interval-based. (This corrected the worklog's interpretation decision #2, which had inverted the PRD meaning.)
- `/home/ubuntu/github/CodingPRD/tasks/task_1339_card_dispute_regulation_e_chargeback/workspace/implementation/start.sh` (infrastructure): the per-boot `python3 -c "import flask"` dependency probe cost ~0.7s of the ~2s server boot; × 560 restarts per 8-round sweep under concurrent host load (~30 sibling pipelines), boots intermittently exceeded the runner's 15s restart poll, causing the "could not be restarted" setup errors and mid-test connection resets. Replaced with a `.deps_ok` stamp file (first boot verifies/installs deps and stamps; subsequent boots cost one `stat`). Boot is now ~0.6s.

**Failure-union analysis:** the union across the first sweep contained 2 deterministic failures (the two fixes above) and 9 environment-induced setup/connection failures across 7 distinct tests with no shared assertion — all resolved by the boot-latency fix and confirmed absent in 16 subsequent clean rounds.

## Step 8: Finalize PRD — 2026-08-12T23:58:45.000Z

Done. PRD_FINALIZED.md is written with a single in-place revision.

## Summary

**Line counts / delta:** PRD.md 237 lines → PRD_FINALIZED.md 237 lines (0% line-count delta; ~207 characters inserted on the single revised line, ~0.4% character delta).

**Changes (one total):**
- §3.5 (Chargeback Filing: Reason Codes, Network Deadlines, and Fees) — revise — inserted a clause into the window-occupancy sentence pinning that occupancy is purely interval-based and status-independent: "occupancy is purely interval-based and does not depend on the chargeback's status, so a `CANCELLED`, `WITHDRAWN`, or otherwise closed chargeback's window blocks exactly as an open one's does until the interval expires" — `implementation/routes_chargebacks.py:83-93`.

**Step 7 diff items that required no PRD edit:**
- `test_09_concurrency_and_read_models.py` missing `set_clock` import — pure test bug; asserted PRD rules (§3.8 status filter, §2.3 pagination meta) already correctly implemented.
- `start.sh` `.deps_ok` stamp — infrastructure only, no PRD-visible behavior.

**Pre-edit search log (mandatory, for the single edit):**
- (a) Subject: the chargeback response-window occupancy gate at filing (`ERR_NETWORK_WINDOW_ACTIVE`) — specifically whether occupancy depends on the prior chargeback's status.
- (b) Paths enumerated and read/grepped: `create_chargeback` occupancy loop (`routes_chargebacks.py:83-93` — iterates all chargebacks on the transaction with no status filter, `filed_at <= now < response_window_end_at`); `response_window_end_at` written once at filing and never mutated (`routes_chargebacks.py:114-116`); `withdraw_chargeback` (`:393-412` — sets `CANCELLED`, retains the window); `escalate` (`:326-385` — `CLOSED_WON`/`CLOSED_LOST`/`WITHDRAWN` closures); `review_representment` ACCEPT path (`:278-318`); chargeback get/list (read-only); repo-wide grep for `response_window_end_at`/`network_window`/`occup` across `implementation/`, `test_helpers/`, `test_suite/` confirming no other occupancy logic exists in `routes_disputes.py`, `helpers.py`, `clock.py`, or elsewhere; test evidence in `test_04_chargeback_filing.py` (`test_refile_inside_response_window_rejected`, `test_refile_after_response_window_succeeds`) pinning that a `CANCELLED` chargeback's window blocks a refile until expiry.
- (c) Wording adjustment: chose a blanket status-independence clause over an exhaustive status enumeration (`CANCELLED`/`WITHDRAWN`/`CLOSED_*` mentioned illustratively) to exactly mirror the code's unfiltered loop; left the half-open interval phrasing and the §3.6 cancelled-window sentence verbatim, since both already match the implementation (boundary `now < response_window_end_at`, gate order state → deadline → occupancy → reason-code, and §3.6's "permitted once the cancelled chargeback's response window no longer occupies the timeline" all verified against `routes_chargebacks.py:78-98`).

## Step 9: PRD Completeness Scan — 2026-08-13T00:09:59.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1339_card_dispute_regulation_e_chargeback/workspace/PRD_COMPLETED.md` produced from `PRD_FINALIZED.md` (which existed; Step 8 had already pinned only the chargeback window-occupancy rule).

**Size**: PRD_FINALIZED.md 237 lines / 40,725 chars → PRD_COMPLETED.md 239 lines / 43,894 chars (+2 lines, +3,169 chars). All changes are in-paragraph inserts/revisions; no new sections.

**Counts**: 17 ambiguity-pins, 3 mismatch-revisions (20 total).

**Mismatch-revisions:**
- §2.4 — revise — mismatch — carved out the envelope's `api_request_timestamp` as wall-clock transport metadata, against the previous blanket "never from the host's wall clock" — implementation/response.py:15-22
- §3.1 — revise — mismatch — new-account rule changed from "posting time falls within thirty days of the account opening" (two-sided reading) to "`posted_at` no later than thirty days after `opened_at`, inclusive; earlier `posted_at` also satisfies" — implementation/helpers.py:201-207
- §3.8 — revise — mismatch — pinned that ledger-driven `outstanding_loss_cents` recomputation does not itself bump the case's `version`/`updated_at`, qualifying §2.5's blanket increment rule (manual posting path never touches the case) — implementation/helpers.py:350-365, routes_disputes.py:520-549

**Ambiguity-pins:**
- §2.2 — insert — ambiguity — unmatched route or unsupported method → `ERR_NOT_FOUND` (HTTP 404) in the standard envelope — implementation/app.py:23-30
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` or negative `offset` → `ERR_INVALID_REQUEST` — implementation/helpers.py:145-161
- §2.3 — insert — ambiguity — filters are exact-match with empty-page semantics, except `type` filters on notifications/loss-recoveries which reject unknown values with `ERR_INVALID_REQUEST` — implementation/routes_disputes.py:508-510, 561-563 vs 280-283, routes_chargebacks.py:151-157
- §2.4 — insert — ambiguity — clock accepts any parseable ISO 8601 instant (forward or backward); unparseable `to_iso8601` → `ERR_INVALID_REQUEST` — implementation/app.py:40-50
- §2.4 — insert — ambiguity — all business timestamps (`opened_at`, `posted_at`, `received_at`, `granted_at`, `filed_at`, `sent_at`, `reversed_at`, deadline/window fields, `current_utc`) render at whole-second `Z` precision; only `created_at`/`updated_at` carry millis — implementation/clock.py:34-42, helpers.py:336-344
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — implementation/helpers.py:179-187
- §2.7 — insert — ambiguity — `expected_dispute_version` must be a positive integer — implementation/routes_disputes.py:334 (via helpers.py:108-112)
- §2.8 — insert — ambiguity — non-amount integer fields (opening balance, report-delay day counts) are non-negative, zero permitted — implementation/helpers.py:113-117
- §3.1 — insert — ambiguity — unparseable `posted_at` → `ERR_INVALID_REQUEST`; stored value normalized to UTC — implementation/routes_accounts.py:105-107, 116
- §3.2 — insert — ambiguity — initial computed-field values at intake: `is_fraud_claim`/`verified_report_delay_days`/`investigation_window_days`/`investigation_deadline_at`/`final_liability_cents` null; `cardholder_keeps_cents`/`outstanding_loss_cents` zero — implementation/routes_disputes.py:235-244
- §3.4 — insert — ambiguity — newly granted credit carries `final_amount_cents` and `reversed_at` as null — implementation/routes_disputes.py:372-383
- §3.4 — insert — ambiguity — directly-created FINALIZED credit gets `amount_cents` = F, `granted_at` = resolution time, `granted_late` false, `reversed_at` null — implementation/routes_disputes.py:103-119
- §3.5 — insert — ambiguity — explicit `amount_cents` is any positive integer, unbounded by claim/transaction — implementation/routes_chargebacks.py:64, 100-102
- §3.5 — insert — ambiguity — chargeback records derived `network_filing_deadline_at` and `response_window_end_at` on itself — implementation/routes_chargebacks.py:113-116
- §3.5 — insert — ambiguity — a `reason_code` outside the eight recognized codes fails at schema tier with `ERR_INVALID_REQUEST` (before compatibility check) — implementation/routes_chargebacks.py:63 (REASON_CODES enum), 96-98
- §3.6 — insert — ambiguity — WON escalation with no open credit creates the credit directly in FINALIZED as in §3.4 — implementation/routes_chargebacks.py:360 via routes_disputes.py:103-119
- §3.6 — insert — ambiguity — a CANCELLED chargeback's `outcome` remains null — implementation/routes_chargebacks.py:404-405
- §3.7 — insert — ambiguity — cooling convention pinned: Mon–Fri dates counted from the day after the notice's sent date through the current date inclusive, must reach three — implementation/clock.py:62-78, helpers.py:375-384
- §3.8 — insert — ambiguity — `memo` is null on the stored entry when omitted (always null on AUTO entries) — implementation/helpers.py:350-360
- §3.8 — insert — ambiguity — Cardholder dispute-list implicitly scoped to own account; explicit foreign `card_account_id` filter → `ERR_FORBIDDEN` — implementation/routes_disputes.py:272-279

No other divergences found: all 27 endpoints, role tables, state machines, fee/liability/holdback formulas, deadline arithmetic, gate orderings, error catalog (IDs + HTTP codes), and cascade side effects in the PRD match implementation/ exactly.
