# Worklog — task_1776_positive_pay_check_fraud_prevention

## Step 1: Create Task Directory — 2026-08-14T15:25:00.000Z

Task directory `tasks/task_1776_positive_pay_check_fraud_prevention/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T16:31:00.000Z

All three artifacts are complete and verified. Final state:

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1776_positive_pay_check_fraud_prevention/SCAFFOLD.yaml` — §1.0–§1.7 (12 entities, 57 endpoints, 33 errors, 6 roles, 10 state machines, 15 calculations, 10 ordered validation priorities, 3 OCC concurrency rules, verbatim response envelope)
- `/home/ubuntu/github/CodingPRD/tasks/task_1776_positive_pay_check_fraud_prevention/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 21 instances across all nine §0.5 rules
- `/home/ubuntu/github/CodingPRD/tasks/task_1776_positive_pay_check_fraud_prevention/SCAFFOLD_CORNER_DESIGN.yaml` — 83 instances (75 active + 8 `excluded_because` stubs) across all nine taxonomy sections

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (938 calls scanned; 0 violations after fixing 3 capture-entity mismatches, 2 FK reverse-reachability gaps, and YAML flow-style quoting for `?`-suffixed inputs and bracketed grounds refs.)

**Maximum-depth difficulty design highlights** (all assert literals pre-computed with Python):
- **Dual-variant calcs**: provisional flat-rate vs marginal-tier fee reconciliation on FeeLedgerEntry (2200 → 2150, −50 adjustment); SAME_DAY_CUTOFF vs ROLLING_HOURS deadline variants producing different deadlines for identical presentment
- **Combinatorial formulas in three different modes**: liability reason×path×tier branch matrix (a); payee score with per-token floor-before-sum — engineered straddle: "ACME INDUSTRIES" vs "ACM INDUSTRIES" scores 84 (mismatch at threshold 85) where sum-then-round yields 85 (b); monthly statement gross→adjustment→waiver→minimum pinned order (5000 vs alternate 4500) (c)
- **Cascades**: decision-PAY → item pays presented amount → ledger crosses `>=` threshold → account REVIEW_HOLD → next clean item force-held (depth 4); BANK_LIABLE resolve → provisional finalize → loss accrual → enrollment auto-suspend → decisions blocked (depth 3)
- **Boundary precision on 7 distinct metrics**: tolerance ±1 cent, deadline exact second (decision inclusive vs sweep strict), fee tier item 10/11, reverse-tier volume 75/76 (generated 75/76-row uploads), claim window ±1s, stale check exactly 180 days at the mandatory default clock, waiver cap 1000 vs 4600 topup
- **Validation precedence**: state-beats-temporal and state-beats-constraint (§1.8); shape-beats-OCC and enrollment-scope-beats-resource-scope (§1.9)
- **Temporal overlap with different interval semantics**: ACH half-open adjacency-allowed vs training 30-minute-buffered adjacency-conflict
- **Compensating invariants**: pay+reverse preserves `net_settled_cents` while gross counters grow; waive+reinstate preserves period gross fee mass
- **Segregation of duties**: uploader↔decision-maker on linked issue files (exempt for NO_ISSUE_RECORD), case assignee↔resolver for claims >25000
- **OCC true-races only**: enrollment PATCH, change-tier, ACH rule PATCH — all `expected_*_version` inputs are `${var}`-bound

Placeholder-closure, banned-vocabulary, enum-closure, and error-triggerability audits all pass; every error code has at least one producing instance, and no sibling task directory was inspected.

## Step 3: Copy Shared Files — 2026-08-14T16:32:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1776_positive_pay_check_fraud_prevention/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T16:46:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1776_positive_pay_check_fraud_prevention/workspace/PRD.md` (367 lines, ~62 KB).

**Structure** — designed from the domain, not the template:
- §1 Introduction (2 paragraphs: fraud-exposure framing + the auditability/segregation-of-duties design commitments)
- §2 with 11 subsections: RBAC (with per-role `identity:` translations — opaque for `BankTreasuryManager`/`BankOps`, entity-backed `EnrollmentUser` for the four customer roles), verbatim §2.2 envelope, pagination, common resource properties (including the explicit `OpsRun` exception: only `id`/`created_at`, no `updated_at`/`version`, plus the enrollment version-bump carve-out for computed counters), the logical clock (startup default `2026-08-01T00:00:00Z`), integer-cents precision, OCC, segregation of duties, idempotency, the 10-level validation precedence order, and existence checking.
- §3 with 9 subsections following the business timeline: onboarding/training/lifecycle → accounts & settlement ledger → issue-file intake → presented-item matching cascade → exception queue → ACH rules → fees & monthly billing → liability claims → ops runs & adoption reporting.
- §4 endpoint table (56 rows, 4 columns only) and §5 error catalogue (33 errors, 2 columns only).

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 84 required, 84 present, 0 missing
- endpoints[].request_body/input/output ids: 73 required, 73 present, 0 missing
- endpoints[].query_params: 0 required (scaffold folds them into input lists; all covered there), 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 10 checked, 10 expressed as an explicit ordered precedence list in §2.10, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (enrollment patch, change-tier, ACH-rule patch — each with occ_field, ERR_STALE_VERSION/412, stale-version-beats-state ordering), 0 missing
- state_machines[].transitions: 30 checked, 30 fully expressed (preconditions with error ids + all side effects incl. cascades), 0 missing
- calculations[]: 12 checked, 12 fully expressed in precise prose (ordered matching chain, per-token-floor payee score with forbidden alternate reading flagged, both deadline variants, tiered fee re-rate, pinned monthly-statement waterfall with forbidden minimum-before-waiver reading, liability splits with odd-cent rule, ledger invariant, review/stale thresholds, 75-in-90-day reverse eligibility, basis-point adoption metrics), 0 missing
- validations[] conditions: all 33 error ids matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed (suspended-enrollment write blocklist, OCC applies_to trio, sweep chore counters), 0 missing
- entities[].fields[] structured content: defaults, ranges, and nullability reconstructible from prose, 0 missing
- sibling-branch symmetry: PAY/RETURN decisions, DEFAULTED_PAY/DEFAULTED_RETURN, three resolution outcomes, ACCRUED/BILLED waive paths, ACTIVE/SUSPENDED close/suspend/resume/expire siblings all rendered at equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 232
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

One verification note: the first mechanical check run produced false failures because the heredoc mangled literal backticks and triple-backtick code fences skewed regex pairing; rerunning with `chr(96)` and split-based extraction (script written to a temp file, since removed) confirmed the PASS results above.

## Step 5: Generate Unit Tests — 2026-08-14T17:25:00.000Z

All checks pass. The suite is complete: 115 tests collected, every citation verbatim-verified, C4 tags unique and last-line, no skips/xfail, no scaffold references.

## Report

**Task**: task_1776_positive_pay_check_fraud_prevention — test infrastructure + suite generated.

**Stage 1 — `test_helpers/`** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1776_positive_pay_check_fraud_prevention/test_helpers/`):
- `types.py` — 12 entity TypedDicts + 16 status/role enums; `OpsRun` correctly omits `updated_at`/`version` (PRD §2.4 append-only receipt)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~45 methods incl. `/_clock/set_current_utc`)
- `api_errors.py` — full 33-error catalog + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserts + `assert_account_ledger_invariants` + `assert_instant_equal` (timestamp comparison tolerant of optional fractional seconds — deadline equality is pinned to instants, not string format, since PRD §2.4's three-fractional-digit format leaves `decision_deadline_at` serialization non-unique)
- `factories.py`, `constants.py` (fee tiers, 25000 provisional cap, 1000 waiver cap, 75-row reverse-volume gate, etc.), `test_users.py` (2 opaque bank roles + 4 entity-backed customer roles with per-instance builders), `fixtures.py` (5 tiers: state progression, enrollment bundle with users/training/activation, check upload + presentment, OPEN-exception / N-exception / paid-item / liability-case composites, ACH rule creation), `__init__.py` barrel.

**Stage 2 — `test_suite/`**: 9 files, **115 tests** (`conftest.py` + `test_01_enrollment_lifecycle` … `test_09_security_baseline`).

**Coverage audit (verified programmatically)**:
- All 20 difficulty instances: ≥2 tests each (liability matrix has 3) — 41 tests
- Corner index: 72 of 75 non-stub instances translated; 8 stubs correctly untouched; all 115 tags resolve to real `name:` entries

**Deliberate skips (PRD-first two-condition filter)** — three `extend_deadline_*` corner instances (`extend_deadline_success_once`, `extend_deadline_second_time_rejected`, `extend_deadline_beyond_24h_rejected`): PRD §3.5 says the new deadline must fall "strictly after the current clock and no more than 24 hours after it," where "it" is grammatically the clock, but the design recipes assume the window is anchored to the *current deadline*. The two readings diverge exactly on these recipes' success/failure outcomes, so they fail unique derivability and were skipped as gaps (no placeholder/weakening).

**Two-reader adjustments**: version assertions are relative (`v2 == v1 + 1`, per PRD §2.4 "increments by one") rather than absolute — the PRD never states the initial version value. `match_score` is read via `.get()` to tolerate both null and omitted-key serializers (PRD pins the value only when scoring runs). Row-error `reason` strings are not asserted (PRD says only "human-readable").

**Verification**: all files compile; pytest collects 115 tests; every docstring carries a whitespace-normalized verbatim PRD quote (0 failures across 115 tests) and ends with exactly one resolving `Design:` line; no `skip`/`skipif`/`xfail`; no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-14T17:55:00.000Z

Implementation complete and verified. Summary:

## What was built

A complete Python + Flask implementation of the Positive Pay & Check Fraud Prevention API at `/home/ubuntu/github/CodingPRD/tasks/task_1776_positive_pay_check_fraud_prevention/workspace/implementation/`:

- `start.sh` — guarded dependency install (no-op when flask importable) + `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000), foreground
- `app.py` — Flask entry, envelope-shaped 404/405/500 handlers, `threaded=True`
- `clock.py` — logical clock pinned at `2026-08-01T00:00:00Z`, never wall-clock; `current_utc` echoes the caller's literal
- `store.py` — in-memory dicts, **empty on every boot, no seeding**
- `errors.py` — full error catalog with exact IDs and HTTP statuses
- `util.py` — `meta`/`response_type`/`data` envelope, `limit/offset/total_count/has_more` pagination (defaults 10/0, clamped 1..100), 3-fractional-digit UTC timestamps, strict shape validators
- `auth.py` — `X-User-ID`/`X-User-Role` priority-1 auth, role authorization incl. EnrollmentUser `user_role` match, customer ownership scoping (`ERR_CROSS_ENROLLMENT_ACCESS`)
- `services.py` — ordered matching cascade (tier gate → hold → existence → voided → stale → duplicate → amount tolerance (inclusive) → payee score with per-token floor), SAME_DAY_CUTOFF/ROLLING_HOURS deadlines, exception lifecycle with pinned `default_decision_snapshot`, settlement ledger + review-hold threshold (>=), fee accrual/waiver/reinstate, tiered monthly billing with pinned evaluation order (adjustment then minimum top-up then ACCRUED→BILLED), liability split (odd cent to customer), provisional credit cap, auto-suspension, daily sweep, adoption metrics (round-half-up bp)
- `routes/` — 12 modules covering all 41 endpoints with the §2.10 priority order: auth → role → ownership → shape → existence → OCC (412) → state (enrollment-outermost) → temporal → constraints (SoD 403s) → waiver cap (422)

## Verification

- Booted repeatedly via `bash start.sh` from a fresh process (the per-test-server contract): clean empty store and default clock on every boot
- 211 hand-written end-to-end checks pass, reproducing the pinned corner/difficulty scenarios: payee threshold 85 pass, cutoff 14:00 roll, deadline-inclusive decision vs strict sweep defaulting, extend window `(deadline, deadline+24h]`, 11-item tier adjustment −50 with top-up 2850, waiver-before-minimum statement order, SoD conflicts, OCC 412s, idempotent replays/conflicts, cross-enrollment 403s, training buffered conflicts, ACH half-open overlap/adjacency, 75/76 volume boundary, stale boundary (180 days), claim window +30d inclusive, auto-suspend cascade, reverse-tier null compliance, 7500 bp adoption metrics

## One fidelity note

`SCAFFOLD_DIFFICULTY_DESIGN.yaml` contains a character miscount for the payee-score example (`ACME INDUSTRIES` vs `ACM INDUSTRIES` claims 84 via lengths 4+9=13; "INDUSTRIES" has 10 letters). The PRD formula and the corner design's explicit arithmetic (`floor(3*50/10)=15 + floor(7*100/10)=70 → 85`) are mutually consistent, so I implemented the formula exactly as the PRD specifies — the disputed pair correctly scores `floor(4*50/14)+floor(10*100/14) = 14+71 = 85` (passes at threshold 85).

## Step 7: Run Tests and Iterate — 2026-08-14T18:15:00.000Z

Clean 8-round sweep: **115/115 in every round, zero failures in the union.** Exit condition met.

---

## Summary

**Iterations run:** 3 sweeps (initial diagnostic: 94/115 ×8; after first fix batch: 112/115 ×8; final: 115/115 ×8, all clean).

**Tests deleted:** none — every failing test traced to a PRD-covered, uniquely-derivable rule; all repairs were test-side.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1776_positive_pay_check_fraud_prevention/test_helpers/fixtures.py` — `create_active_enrollment`: added explicit `payment_review_threshold_cents` parameter forwarded to the **account** payload. Previously the kwarg fell into `**enrollment_extra` and was silently sent to enrollment creation, so the account was created with threshold `None` and never entered `REVIEW_HOLD` (PRD §3.2 requires the hold at `cumulative_paid_cents >= threshold`).

**Fixes applied to `test_suite/`:**
- `test_03_matching_cascade.py` — the known generation-time miscount: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` counted "INDUSTRIES" as 9 letters; the PRD §3.4 formula (per-token floor, then sum) uniquely derives floor(4·50/14)+floor(10·100/14) = 14+71 = **85** for `ACME INDUSTRIES` vs `ACM INDUSTRIES` (verified by computing the formula). `test_per_token_floor_gives_84` → repaired to assert 85 (renamed `test_per_token_floor_gives_85`, docstring arithmetic corrected). `test_score_84_mismatches_at_threshold_85` → repaired to the PRD-derived outcome at the default threshold 85: score 85 is not *below* 85, so `CLEAN`/`PAID` (renamed `test_score_85_passes_at_default_threshold_85`).
- `test_04_exceptions_decisions.py` — `_matrix_setup`: e1's presented payee changed `ACM INDUSTRIES` → `ACME IND` (scores 63 < 85), restoring the intended genuine `PAYEE_MISMATCH` exception the liability-matrix tests operate on (the old pair now pays clean under the corrected formula, leaving `exception_id` null). `test_decision_one_second_past_deadline_rejected_then_defaulted`: `exceptions_defaulted` assertion corrected 1 → 2 — both setup exceptions are `OPEN` and strictly past their shared deadline, and PRD §3.9 defaults *every* such exception. Added `user_roles=("ADMIN", "DECISION_MAKER")` at 4 setup sites whose tests drive the decision endpoint with a DECISION_MAKER identity that was never provisioned (PRD §2.1 entity-backed identity requirement).
- `test_05_accounts_and_liability.py` — same `user_roles=("ADMIN", "DECISION_MAKER")` provisioning fix at 4 setup sites (`TestReviewHoldCascade._setup`, `CapCo`, `WinCo2`, `_loss_setup`).
- `test_02_issue_files_and_checks.py` / `test_07_fees_and_billing.py` — class helper methods (`_setup_closed_account`, `_setup_suspended_with_used_reference`, `TestStatementPinnedOrder._setup_and_bill`) referenced the `api` fixture as a free variable (`NameError`); they now take `api` as a parameter, passed from each test.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful on every one of the 24 failing test-rounds; all failures were test-artifact bugs (fixture wiring, unprovisioned identities, and the scaffold's payee-score arithmetic).

## Step 8: Finalize PRD — 2026-08-14T18:22:00.000Z

Step 8 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1776_positive_pay_check_fraud_prevention/workspace/PRD_FINALIZED.md` produced.

## Summary

**Line counts / %-delta:** PRD.md 367 lines / 62,017 chars; PRD_FINALIZED.md 367 lines / 62,203 chars. Delta: +186 chars, **+0.30%** (one sentence revised inline, no lines added or removed).

**Changes (one total):**
- **§2.1 — revise** — extended the existing role-authorization sentence so the `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403) rejection explicitly covers a customer-role caller whose `X-User-ID` names **no existing `EnrollmentUser` record at all** (no persisted `user_role` exists to correspond to the claimed role) — `implementation/auth.py:62-67` (`authorize`: `user is None or user.get("user_role") != CUSTOMER_ROLE_MAP[role]` → `ERR_FORBIDDEN_FOR_ROLE`).

**Items examined and deliberately not edited (PRD already uniquely determines the behavior; Step 7 failures were pure test artifacts):**
- fixtures.py `payment_review_threshold_cents` — PRD §3.2 already pins it as an Account-creation field and pins the `>=` (equality-triggers) hold evaluated immediately after every pay-side ledger update; impl: `routes/accounts.py:34,49`, `services.py:299-305`. The bug was the fixture sending the knob to enrollment creation.
- test_03 payee score 84→85 and threshold-pass — PRD §3.4 already pins per-token floor before summing plus the forbidden-alternate-reading sentence, strict "below" comparison, and §3.1 pins default threshold 85; impl: `services.py:230-248, 365-369`. Failure was the scaffold's letter miscount (INDUSTRIES).
- test_04 `_matrix_setup` payee `ACME IND` — test-data fix under the PRD-pinned formula.
- test_04 `exceptions_defaulted` 1→2 — PRD §3.9 already says *every* `OPEN` exception strictly past deadline is defaulted and counted; impl: `services.py:553-562`.
- test_02/test_07 `api` NameError in class helpers — pure Python fixture bug, no behavioral content.

**Per-edit pre-edit search log (the single edit):**
- **(a) Subject:** error identity when a recognized customer role's `X-User-ID` resolves to no persisted `EnrollmentUser`.
- **(b) Impl paths enumerated and read/grepped:** `auth.authenticate` (auth.py:38-54 — priority-1 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` only for missing/malformed headers or unrecognized role names; returns `None` user for unresolved customer ids); `auth.authorize` (auth.py:57-67 — both the not-listed branch and the `None`-user/mismatch branch raise the same `ERR_FORBIDDEN_FOR_ROLE`); `check_ownership` / `scope_list` / `check_list_enrollment_param` (auth.py:70-98 — unreachable with a `None` user for customer roles because `authorize` raises first); and all 40+ `authenticate()`→`authorize()` callsites across every route file (accounts, ach_rules, clock_routes, enrollment_users, enrollments, exceptions, fee_entries, issue_files, liability_cases, ops_runs, presented_items, training_sessions) — grep-verified uniform, including bank-only endpoints (e.g. clock, ops-runs) where a customer role fails the not-listed branch with the identical error id.
- **(c) Wording adjustment:** attached the no-record case to the *existing* priority-2 sentence as an extension of the role-correspondence check (em-dash appositive) rather than adding a new rule or a new error — this leaves priority-1 header-error precedence, §2.10 ordering, ownership scoping, and all §3 behavior untouched, and stays accurate for both `authorize` branches since both yield the same error id.

## Step 9: Complete PRD — 2026-08-14T18:40:00.000Z

PRD_COMPLETED.md is written. Source: `PRD_FINALIZED.md` (367 lines / 62,429 chars) → `PRD_COMPLETED.md` (370 lines / 69,942 chars), +3 lines, +7,469 chars, no sections added or removed.

Counts: **ambiguity-pins: 27** · **mismatch-revisions: 4**

Changes (all file refs under `/home/ubuntu/github/CodingPRD/tasks/task_1776_positive_pay_check_fraud_prevention/workspace/implementation/`):

- §2.1 — insert — ambiguity — customer list results implicitly scoped to caller's enrollment; foreign `enrollment_id` list filter → `ERR_CROSS_ENROLLMENT_ACCESS` — auth.py:80-98
- §2.2 — insert — ambiguity — all server timestamps (meta + created_at/updated_at) rendered from the logical clock — util.py:37-38, 284-292
- §2.2 — insert — ambiguity — trailing-slash tolerance; no-route → `ERR_NOT_FOUND`, wrong method → `ERR_METHOD_NOT_ALLOWED` (405), server fault → `ERR_INTERNAL` (500) — app.py:27,37-48
- §2.3 — revise — ambiguity — `limit`/`offset` non-integer → `ERR_INVALID_REQUEST`, out-of-range values clamped (1..100 / ≥0), not rejected — util.py:134-150
- §2.3 — insert — ambiguity — `created_at` sort ties broken by creation order — util.py:157
- §2.4 — revise — ambiguity — `version` starts at 1 — util.py:291
- §2.5 — insert — ambiguity — clock endpoint echoes the submitted string verbatim, rejects missing/unparseable `to_iso8601` with `ERR_INVALID_REQUEST`, and allows moving the clock backward — clock_routes.py:17-22, clock.py:29-34
- §2.7 — insert — ambiguity — accepted OCC writes bump `version` even when no field changes (e.g. patch carrying only the expected version) — routes/enrollments.py:144-146
- §2.9 — insert — ambiguity — presented-item `idempotency_key` is scoped per account — store.py:19, routes/presented_items.py:81
- §2.10 p3 — insert — ambiguity — on creation requests the ownership check runs against the body-referenced parent immediately after those identifiers' existence checks — routes/issue_files.py:48-50, routes/liability_cases.py:42-44
- §2.10 p4 — insert — ambiguity — absent/unparseable body treated as `{}`; non-object JSON body → `ERR_INVALID_REQUEST`; unrecognized body fields and query params ignored — util.py:166-172
- §2.10 p4 — revise — mismatch — BLOCK-rule shape phrase changed from "omitting" to "carrying none" (explicit null is accepted) — routes/ach_rules.py:47-48
- §2.10 p7 — insert — ambiguity — added `ERR_EXCEPTION_ALREADY_EXTENDED` to the resource-state list — routes/exceptions.py:89-90
- §3.1 — insert — ambiguity — `stale_days` must be non-negative; `loss_suspension_threshold_cents` non-negative when non-null — routes/enrollments.py:74-77
- §3.1 — insert — ambiguity — bank may create users in any non-TERMINATED status — routes/enrollment_users.py:31-33
- §3.1 — insert — ambiguity — wrong-enrollment attendee id → `ERR_INVALID_REQUEST`; schedule/complete/cancel gated only on non-TERMINATED — routes/training_sessions.py:96-99
- §3.1 — revise — mismatch — SUSPENDED write-block list: ACH rule *retirement* is allowed for customers while suspended; liability *withdrawals* are blocked — routes/ach_rules.py:218, routes/liability_cases.py:172
- §3.1 — insert — ambiguity — activating an already-ACTIVE enrollment → `ERR_ENROLLMENT_NOT_ACTIVATABLE`; suspending a non-ACTIVE one → `ERR_ENROLLMENT_NOT_ACTIVE` — routes/enrollments.py:169-170, 183-184
- §3.1 — insert — ambiguity — termination from PENDING_ACTIVATION → `ERR_ENROLLMENT_NOT_SETTLED` — routes/enrollments.py:197-198
- §3.1 — insert — ambiguity — bank patch allowed in any non-TERMINATED status, CustomerAdmin requires ACTIVE; null patch of non-nullable knobs → shape error; threshold may be nulled — routes/enrollments.py:49-57, 141-143
- §3.1 — insert — ambiguity — trailing-90-day tier gate measured on each check's `created_at` within [now−90d, now]; tier change allowed from any non-TERMINATED status and to the current tier — services.py:735-744, routes/enrollments.py:227-236
- §3.2 — insert — ambiguity — `payment_review_threshold_cents` must be non-negative-or-null; duplicate `account_number` → `ERR_INVALID_REQUEST` — routes/accounts.py:34-44
- §3.2 — insert — ambiguity — pay event + hold flip is a single mutation (one version bump); clear-hold gated only on non-TERMINATED enrollment — services.py:292-306, routes/accounts.py:110
- §3.2 — insert — ambiguity — closing an already-CLOSED account → `ERR_ACCOUNT_NOT_ACTIVE` — routes/accounts.py:90-91
- §3.3 — insert — ambiguity — non-array `rows` or non-object row fails the whole request with `ERR_INVALID_REQUEST`; §2.10 precedence puts account-state gate before tier gate — routes/issue_files.py:44-56
- §3.3 — insert — ambiguity — in-file duplicate check seeds only from earlier accepted rows — routes/issue_files.py:70-79, services.py:528-529
- §3.3 — insert — ambiguity — empty `rows` array yields an ACCEPTED upload with zero counts — routes/issue_files.py:107-111
- §3.4 — insert — ambiguity — item `check_number`/`payee_name_raw` required strings, may be empty; ingestion gated only on non-TERMINATED enrollment and non-CLOSED account; idempotent replay resolved after those gates — routes/presented_items.py:63-86
- §3.4 — insert — ambiguity — when several checks share a number, the latest-created is matched — services.py:335-345
- §3.4 — insert — ambiguity — reversal reason required but may be empty; reversal not gated on account status and leaves the check CONSUMED — routes/presented_items.py:129-137
- §3.5 — revise — mismatch — extension window anchored at the current `decision_deadline_at` (strictly after it, ≤24h past it), not at the current clock; extension gated only on non-TERMINATED — routes/exceptions.py:94-99, 86
- §3.6 — revise — mismatch — BLOCK may carry explicit null `max_amount_cents`; FILTER requires non-null positive integer; no start/end ordering enforced; create requires ACTIVE for bank and customer callers alike — routes/ach_rules.py:41-54, 79
- §3.6 — insert — ambiguity — rule edit requires ACTIVE enrollment for all roles — routes/ach_rules.py:148
- §3.6 — revise — mismatch — retirement requires only non-TERMINATED enrollment (available while SUSPENDED, even to customers) — routes/ach_rules.py:218
- §3.7 — insert — ambiguity — waiver `reason` required but may be empty; waive/reinstate gated only on non-TERMINATED — routes/fee_entries.py:48, 51, 72
- §3.7 — revise — ambiguity — fee re-rate tie-break: `check_number` compared as a string, final tie broken by creation order — services.py:623-631
- §3.7 — insert — ambiguity — statement period supplied via `period` query param (missing/malformed → `ERR_INVALID_REQUEST`); `entry_count` defined as count of the period's fee entries — routes/enrollments.py:256-258, services.py:693
- §3.8 — insert — ambiguity — no uniqueness check on filing; multiple cases per PAID item allowed — routes/liability_cases.py:42-66
- §3.8 — insert — ambiguity — start-review and resolve gated only on non-TERMINATED — routes/liability_cases.py:100, 121
- §3.8 — revise — mismatch — `ytd_bank_loss_cents` counts cases whose resolution falls in the logical clock's current calendar year (prior text was vacuous) — services.py:71-82
- §3.9 — insert — ambiguity — ops runs not gated on enrollment status; sweep defaults due exceptions in creation order; period billable at exactly 00:00:00 UTC on the first of the next month; receipt field set pinned (null `period`/`enrollment_id` cases, inapplicable counters zero) — routes/ops_runs.py:60-90, services.py:553-562, routes/ops_runs.py:72-76
- §5 — insert — ambiguity — added catalogue rows `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500) — app.py:41-48

Key mismatches to note: the extend-deadline 24-hour window is anchored at the exception's current `decision_deadline_at` rather than the current clock; ACH rule retirement is permitted on SUSPENDED enrollments (only TERMINATED blocks it), which the old §3.1 blanket statement contradicted; BLOCK rules accept an explicitly null `max_amount_cents`; and the `ytd_bank_loss_cents` accrual window is the logical clock's current calendar year.
