# Worklog — task_1965_employee_referral_program_administration

## Step 2: Generate Scaffold — 2026-08-15T04:14:31.473Z

Scaffold generation complete. All three artifacts written and lint-clean.

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1965_employee_referral_program_administration/SCAFFOLD.yaml` (§1.0–§1.7)
- `/home/ubuntu/github/CodingPRD/tasks/task_1965_employee_referral_program_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single `scaffold_difficulty_design` key)
- `/home/ubuntu/github/CodingPRD/tasks/task_1965_employee_referral_program_administration/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single `scaffold_corner_design` key)

**Counts**
- Entities: 11 (Employee, Candidate, JobRequisition, PolicyVersion, Campaign, Referral, BonusMilestone, PayrollBatch, AbuseCase, TaxProfile, ReferralEvent)
- Endpoints: 72 (incl. `/_clock/set_current_utc` with the mandatory 2026-08-01T00:00:00Z default and an `/_ops/evaluate` sweep)
- State machines: 10 (Referral has 17 states with two cycles; JobRequisition OPEN↔PAUSED; Campaign ACTIVE↔EXHAUSTED; milestone PAID→CLAWED_BACK)
- Calculations: 11 (incl. dual-variant FLAT vs AGGREGATE withholding, raw vs Beta-smoothed source quality, provisional vs committed cap accumulators, decayed fraud risk score)
- Validations: 28 rows across 13 ordered priority tiers; Errors: 28; Concurrency (OCC) rules: 3; Roles: 7 (segregation-of-duties model: PayrollProcessor prepares / TalentAdmin confirms payment; abuse-case raiser cannot decide own case)
- Difficulty-design instances: 23 (3+3+3+2+2+3+3+2+2 across the nine rules — all §0.5 differentiation clauses honored: distinct entity domains, formula modes a/b/c, distinct cascade triggers, distinct error-category pairs, distinct boundary metrics/endpoints, distinct entity pairs, closed vs half-open interval semantics, campaign-budget vs batch-money conserved quantities)
- Corner-design instances: 55 active + 14 `excluded_because` stubs; all instance names unique across both files

**Verification performed**
- `scaffold_lint.py` verdict: `VERDICT: clean lint` (971 calls scanned, all FKs reverse-reachable)
- Placeholder-closure audit: every `${var}` bound by an earlier `captures:` in its instance (zero unbound)
- Every formula-derived assert literal recomputed with code (tenure 90/89-day boundary, cooldown month-clamp to 2026-02-28, retention due 2027-01-28, clawback until 2027-04-28, split 275001 → 82500/192501, AGGREGATE bracket straddles 6500/9250/48750, 5/11 smoothing = 0.454545, etc.)
- Error catalog: every error referenced by a validation/transition/OCC rule; no forbidden race vocabulary anywhere

**Notable design decisions**
- PolicyVersion pinning: each referral snapshots the ACTIVE policy at submission, so rule constants (tiers, cap, retention days) are stable per-referral while policies supersede over half-open effectiveness windows.
- Campaign accounting invariant `reserved + spent + remaining == budget` with reserve-at-submission, convert-at-earn, release-on-terminal/forfeit/clawback; EXHAUSTED at `spent == budget` with auto-reopen on release — drives both a difficulty cascade and a conservation invariant.
- Provisional-vs-committed annual cap gap: quotes clip against provisional (includes EARNED) while approval enforces committed (APPROVED+ only), which makes the aggregate-validation corner (`annual_cap_exceeded_at_approve`) reachable without any race.
- The hire cascade (milestones → campaign settlement → requisition FILLED → sibling NOT_SELECTED) and the abuse-confirm cascade (referral FORFEITED → BATCHED milestone detached → batch totals recompute + version bump) provide the two distinct-trigger transitive chains.

Difficulty target honored: requester asked for harder-than-expert level; scaffold was pushed to maximum depth/breadth per the difficulty-target instruction (23 difficulty instances across 9 rules, 55 active corner instances, 11 entities, 72 endpoints, 28 validations in 13 priority tiers).

## Step 3: Copy Shared Files — 2026-08-15T04:14:57.365Z

Copied `./INSTRUCTION.md` to `tasks/task_1965_employee_referral_program_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T04:31:37.643Z

PRD generation complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1965_employee_referral_program_administration/workspace/PRD.md` — 382 lines (dense long-form prose, ~9,500 words).

**Section list:**
- §1 Introduction (2 paragraphs: business context + four design commitments)
- §2 Global Specifications: 2.1 RBAC (7 roles with identity translations), 2.2 API Response Structure (byte-verbatim canonical block, diff-verified), 2.3 Pagination, 2.4 The Logical Clock and Program Time (startup default `2026-08-01T00:00:00Z`, non-monotone, calendar-year and month-clamping conventions), 2.5 Resource Identity and Common Fields (incl. ReferralEvent's absent `updated_at`/`version`), 2.6 Money/Rates/Rounding, 2.7 OCC (3 rules, explicit check ordering), 2.8 The Pinned Policy, 2.9 Nested Path Resolution, 2.10 Validation Pipeline and Error Precedence (global priority order 1–7, `ERR_INVALID_STATE` vs `ERR_ALREADY_TERMINAL`), 2.11 Referral Audit Trail
- §3 Business Logic (8 subsections): 3.1 Employees/Tax Profiles/Offboarding, 3.2 Requisitions/Policies/Campaigns, 3.3 Referral Submission (10-step ordered eligibility gauntlet + 6-step pinned bonus quote), 3.4 Recruiting Pipeline, 3.5 Milestones/Retention/Clawback, 3.6 Payroll (withholding variants, batching, SoD confirmation), 3.7 Abuse/Risk Scoring/Compliance, 3.8 Source-Quality Analytics
- §4 Endpoint Definitions (72-row table, 4 columns only)
- §5 Error Code Catalogue (28 rows, 2 columns only)

**Hard Contract Reports:**
- Contract 1 (Field-Name Coverage): 120 required identifiers (entity fields + request bodies + query/path params + common fields), 120 present in backticks, 0 missing — **PASS**
- Contract 2 (Rule Coverage): all 10 state machines' transitions/preconditions/side effects expressed (including the 30+-transition Referral machine and all cascade settlements); all 11 calculations in reconstructible prose (tenure, cooldown, bonus quote, milestone split, dual-variant withholding, annual accumulators, campaign settlement invariant, risk decay, velocity, source quality, ring detection); all 28 validations matchable to their error IDs with explicit priority orderings (global pipeline, submission gauntlet 8→11→12→13→14→15→16→17→18→19, campaign activation 19→22, approve 25→26, OCC 9 before business rules); all 3 OCC rules named with field + `ERR_STALE_VERSION`/412; sibling branches given equal density (3 reject reasons, 7 withdraw states, 8 forfeit states, 4 campaign-end states) — **PASS**
- Contract 3 (§3 Path Purity): 717 backtick tokens scanned in §3, 0 path tokens, 0 bare-method tokens, 0 method+path combos — **PASS**

**Scaffold coverage:** every scaffold section fully translated — §1.0 envelope (§2.2 verbatim + §2.3), §1.1 all 11 entities, §1.2 all 10 state machines, §1.2.1 all 3 concurrency rules, §1.3 all 11 calculations, §1.4 all 28 validations, §1.5 all 72 endpoints, §1.6 all 28 errors (each mentioned in §2/§3 prose near its trigger), §1.7 all 7 roles. The difficulty-design and corner-design files were never opened.

Two interpretation notes for downstream consumers: (1) cancel-on-non-OPEN-batch maps to the generic state errors (`ERR_INVALID_STATE`/`ERR_ALREADY_TERMINAL`), with `ERR_BATCH_NOT_OPEN` reserved for milestone add/remove per the scaffold's `applies_to`; (2) preconditions without a scaffold-nominated error ID (e.g., future-dated policy activation, departure of a non-HIRED candidate) are explicitly assigned the generic `ERR_INVALID_STATE` fallback, stated as a rule in §2.10.

## Step 5: Generate Unit Tests — 2026-08-15T05:08:48.541Z

All green. Final state:

## Summary

**Files written** under `/home/ubuntu/github/CodingPRD/tasks/task_1965_employee_referral_program_administration/`:

`test_helpers/` (9 files):
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 11 status enums, role enum, 11 entity TypedDicts (`ReferralEvent` correctly omits `updated_at`/`version` per its append-only semantics)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all 48 endpoints from the PRD table)
- `api_errors.py` — 28 `ApiErrorId` members + HTTP status map registered with `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus `assert_campaign_invariant` / `assert_batch_totals`
- `factories.py` — payload factories (input fields only) with unique-value counter
- `constants.py` — policy defaults, thresholds, risk weights, clock constants
- `test_users.py` — `TEST_USERS` shared headers + `make_employee_headers` / `make_recruiter_headers` / `make_hiring_manager_headers` per-instance builders for the three entity-backed roles
- `fixtures.py` — composite setup helpers (policy activation, open requisition, verified tax profile, full referral-to-hired pipeline, milestone fetch/approve, batch add/remove, clock set, ops sweep, abuse raise/confirm, suspension setup)

`test_suite/` (16 files): `conftest.py` + 15 test modules (`test_01_submission_eligibility` … `test_15_occ_and_consistency`).

**Test counts per design queue:**
- Queue A (Difficulty): 23 instances × 2 tests = **46 tests** — every instance covered.
- Queue B (Corner): 55 non-stub instances × 1 test = **55 tests** — every non-stub covered; 13 `excluded_because:` stubs not translated (their cross-references were verified to resolve to real difficulty instances).
- **Total: 101 test functions.**

**Instances skipped:** none — every non-stub instance in both queues passed the PRD-first two-condition filter. One corner instance's recipe (`employee_terminate_forfeits_unpaid_milestones`) contained an assert contradicting PRD §3.1 ("Milestones still `PENDING` … are not touched by termination" vs. the recipe's "both milestones FORFEITED"); the emitted test asserts only the PRD-supported claims (EARNED hire milestone FORFEITED, referral remains HIRED), per the PRD-is-the-contract rule.

**Design-tag audit:** all 101 tests carry exactly one `Design:` tag as the last docstring line; every tag resolves to a real instance name in the source YAML (verified programmatically); no stub tags used; no `skip`/`skipif`/`xfail` markers anywhere.

**PRD-citation audit:** every test docstring carries verbatim PRD quotes — verified by literal substring match against `PRD.md` (multi-window scan, 0 misses after expanding all ellipsis-compressed quotes to full sentences).

**Sanity checks:** all files compile, all test modules import with the framework on `PYTHONPATH`, no "scaffold" mentions in generated code.

## Step 6: Generate Implementation — 2026-08-15T05:10:53.593Z

# Implementation Complete: task_1965 Employee Referral Program Administration

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1965_employee_referral_program_administration/workspace/implementation/`)

- `start.sh` — guarded dependency install (`pip install` only when `flask` import fails), `exec python3 app.py` in foreground, `$PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — `flask>=3.0` (already present on host)
- `app.py` — Flask entry, global RLock per request, auth before-request hook, envelope error handlers (404/405 → `ERR_NOT_FOUND` envelope)
- `db.py` — in-memory dict store + logical clock (default exactly `2026-08-01T00:00:00Z`); **no seeding, no disk persistence anywhere** (verified by grep)
- `errors.py`, `util.py` (ISO-8601 3-fractional-digit timestamps, round-half-up Decimal money, calendar-month clamp math, envelope/pagination/shape validators), `middleware.py` (7-role header auth), `services.py` (all computed fields, settlement, cascades, sweep), `views.py` (whitelisted serializers — internal fields like `_paid_at`/`_seq` never leak)
- `routes/`: `ops`, `employees`, `candidates`, `requisitions`, `policies`, `campaigns`, `referrals`, `milestones`, `batches`, `abuse`, `analytics` (~3,150 lines total)

## Endpoint count: 72/72 from the scaffold endpoint table

## State machines implemented (10)
Employee (ACTIVE→TERMINATED with milestone-forfeiture cascade), Candidate (AVAILABLE/IN_PROCESS/HIRED/DEPARTED with cooldown stamping), JobRequisition (DRAFT/OPEN/PAUSED/FILLED/CANCELLED with REQ_FILLED/REQ_CANCELLED NOT_SELECTED cascades), PolicyVersion (half-open window conflict, supersede-on-activate, future-activation rejection), Campaign (DRAFT/ACTIVE/PAUSED/EXHAUSTED/ENDED/CANCELLED with closed-window conflict and reservation releases), Referral (17 states; full recruiter/HM pipeline, offer-decline loop, withdraw, reject reason codes, expiry, FORFEIT cascade), BonusMilestone (PENDING→PAID plus forfeiture/clawback, recovery lines), PayrollBatch (OPEN→SEALED→EXPORTED→CONFIRMED_PAID / CANCELLED with detach cascades), AbuseCase (OPEN/UNDER_REVIEW→CONFIRMED/DISMISSED with SoD), TaxProfile (SUBMITTED↔VERIFIED).

## Calculations implemented (11)
tenure_days (floor, clamped ≥0), candidate_cooldown (calendar-month day-clamp; allowed exactly at `cooldown_until`), bonus_quote (pinned 6-step order: tier → campaign attach → round-half-up uplift clipped to remaining budget, EXECUTIVE zero-uplift attachment, provisional-cap clip floored at 0), milestone_split (HIRE rounded first, RETENTION absorbs remainder), tax_withholding (FLAT bps override + AGGREGATE 3-bracket marginal, exact Decimal, approval-order-dependent), annual accumulators (provisional/committed lenses, calendar-year by `earned_at`, CLAWED_BACK subtraction), campaign_settlement (reserve/convert/release with `reserved+spent+remaining == budget` invariant, EXHAUSTED↔ACTIVE auto-flips), fraud_risk_score (180-day half-life decay, half-up, cap 500, suspension ≥100), velocity auto-case (≥ limit over closed 7-day window), duplicate-ring (≥3 distinct referrers, 90-day window), source_quality analytics (raw + beta-smoothed K=5 rates, 6-dp half-up).

## Boot sanity check: PASS
Fresh `bash start.sh` on port 18255 → employee create 201, list `total_count: 1`; killed; fresh boot on 18256 → list `total_count: 0` (empty state confirmed), clock endpoint 200. Additionally, three end-to-end batteries (110+ assertions covering the full submission gauntlet precedence, hire/retention/clawback sweeps, OCC 412s, campaign budget floor, SoD, termination and abuse cascades, AGGREGATE ordering, cooldown boundaries) all passed against fresh boots. The only failures observed during testing were bugs in my own smoke-script expectations (pagination default, year-rollover accumulators, impossible open-ended-policy supersede); every one was verified to be correct literal-PRD behavior in the implementation before adjusting the script.

## Diagnostic iteration — 2026-08-15 (test+fix loop to green)

Initial 8-round parallel sweep: 89/101 in every round (12 deterministic failures, zero flakiness).
Final 8-round parallel sweep after fixes: **101/101 in all 8 rounds**.

**test_helpers/assertions.py** — added `assert_instant_eq` (serialization-agnostic instant
comparison): PRD pins the *instant* of derived/stamped datetime fields and three fractional
digits only for `created_at`/`api_request_timestamp`; exact-string equality on
`cooldown_until`/`retention_due_at`/`clawback_until`/`submitted_at`/`last_terminal_outcome_at`
over-specified a PRD-silent serialization detail.

**test_suite fixes (8 tests)**
- test_03 (×2, `TestBonusQuoteEvaluationOrderCapClip`): cap 100000 clipped the *first*
  referral's own gross at submission (PRD §3.3 step 6), making the expected 45000/55000
  figures internally inconsistent; raised cap to 200000 and corrected expected gross to
  155000 (uplift 125000 pre-clip unchanged).
- test_04 (`test_approve_order_changes_aggregate_withholding`): second approval's
  cumulative base only changes via `ytd_paid_gross_cents`, which PRD increments solely at
  payment confirmation; inserted batch/seal/export/confirm-paid of the first milestone
  between the two approvals so 9250 then 48750 is uniquely derivable under both PRD readings.
- test_05 (`test_campaign_budget_restored_after_abuse_forfeiture` → renamed
  `..._after_milestone_forfeiture`): abuse-confirm cascade cannot fire on the COMPLETED
  referral (PRD §3.7 gates it to "still non-terminal — SUBMITTED through HIRED"); rewrote
  the restoration trigger as manual forfeit of the two EARNED milestones (PRD §3.6), keeping
  the (0/200000/0)→(0/0/200000) + EXHAUSTED→ACTIVE assertions.
- test_08/test_09/test_10/test_15 (4 tests): switched 6 exact timestamp string assertions
  to `assert_instant_eq`.
- test_09 (`test_batch_add_after_seal_returns_batch_not_open`): supplied the batch's
  post-seal current version (PRD §2.7 reports ERR_STALE_VERSION before ERR_BATCH_NOT_OPEN).
- test_12 (`test_duplicate_referral_...`): withdrawal stamps `last_terminal_outcome_at`,
  starting a fresh 6-month cooldown; advanced the clock to exactly `cooldown_until`
  (2027-02-01, allowed per PRD) before the re-submission.
- test_12 (`test_annual_cap_exceeded_at_approve`): the 2027 clock move reset the
  calendar-year accumulator so no cap breach could fire; hires now dated 2026-01-01
  (retention due 2026-06-30) and the sweep runs unmoved at 2026-08-01, keeping the whole
  scenario inside the 2026 accumulator window.

**implementation/services.py** — `forfeit_milestone` and the sweep clawback leg now release
the milestone-kind's own corresponding earned share (hire share / retention share) instead
of deriving the retention share as `uplift_spent_cents - hire_share`, which under-released
when the hire share had already been released (double-release scenario exercised by the
rewritten test_05). Clamping against campaign `spent_cents` retained as a safety net.

**Assertion removals (unique-derivability)** — test_11
`test_clawback_of_paid_retention_after_late_departure`: dropped the two post-clawback
accumulator value assertions; PRD §3.5's status-set formula ("sums ... PAID ... then
subtracts ... CLAWED_BACK") and its clawback sentence ("the accumulators subtract the
milestone's amount_cents") admit two divergent readings for a PAID→CLAWED_BACK milestone
(−210000 vs 0), so neither value is uniquely derivable. All other assertions (CLAWED_BACK
status, recovery_status PENDING, sweep tally, referral stays COMPLETED) retained. No whole
test deletions.

## Step 7: Run Tests and Iterate — 2026-08-15T05:39:53.983Z

Clean 8-round parallel sweep: **101/101 passed in every round** (808/808 total test executions). Exit criteria met.

## Summary

**Iterations run:** 2 sweeps (initial 8-round sweep → 12 deterministic failures, identical in all 8 rounds; fixes applied; sanity round 101/101; final 8-round sweep all green).

**Tests deleted:** None. One assertion-level removal under the unique-derivability rule:
- `test_11_sweep_and_clawback.py::test_clawback_of_paid_retention_after_late_departure` — removed the two post-clawback accumulator value assertions (`annual_provisional_cents == 0`, `annual_committed_cents == 0`). PRD §3.5's status-set formula ("sums ... `PAID` ... then subtracts ... `CLAWED_BACK`" → −210000) and its clawback side-effect sentence ("the referrer's annual accumulators subtract the milestone's `amount_cents`" → net 0) admit two divergent PRD-faithful implementations for a PAID→CLAWED_BACK milestone, so no value is uniquely derivable. All other assertions (CLAWED_BACK, recovery PENDING, sweep tally, referral stays COMPLETED) retained.

**Fixes applied to `test_helpers/`:**
- `assertions.py` — added `assert_instant_eq`: compares timestamps by parsed instant. PRD pins the *instant* of clock-derived fields but fixes the three-fractional-digit serialization only for `created_at`/`api_request_timestamp`; exact-string equality on `cooldown_until`/`retention_due_at`/`clawback_until`/`submitted_at`/`last_terminal_outcome_at` over-specified a PRD-silent serialization detail.

**Fixes applied to `test_suite/` (8 tests):**
- `test_03` (×2, `TestBonusQuoteEvaluationOrderCapClip`): setup's 100000 cap clipped the *first* referral's own gross at submission per PRD §3.3 step 6, making the expected 45000/55000 figures self-inconsistent; cap raised to 200000 with corrected expected gross 155000 (uplift 125000 pre-clip unchanged).
- `test_04::test_approve_order_changes_aggregate_withholding`: the second approval's AGGREGATE base changes only via `ytd_paid_gross_cents`, which PRD increments solely at payment confirmation; inserted batch→seal→export→confirm-paid of the first milestone between approvals so 9250→48750 is uniquely derivable.
- `test_05`: renamed to `test_campaign_budget_restored_after_milestone_forfeiture` — the abuse-confirm cascade cannot fire on a COMPLETED referral (PRD §3.7 gates it to "still non-terminal — in any state from `SUBMITTED` through `HIRED`"); restoration trigger changed to PRD §3.6 manual forfeit of both EARNED milestones, keeping the EXHAUSTED→ACTIVE and (0/0/200000) assertions.
- `test_08`/`test_09`/`test_10`/`test_15` (4 tests): 6 exact-string timestamp assertions switched to `assert_instant_eq`.
- `test_09::test_batch_add_after_seal_returns_batch_not_open`: was passing the pre-seal batch version; per PRD §2.7 the stale-version check precedes the batch-open check, so the test now supplies the post-seal current version to reach `ERR_BATCH_NOT_OPEN`.
- `test_12::test_duplicate_referral_...`: after withdrawal the candidate's fresh cooldown (2027-02-01) blocked the re-submission with `ERR_CANDIDATE_IN_COOLDOWN` (correct gauntlet order); clock advanced to exactly `cooldown_until` (allowed per PRD) before re-submitting.
- `test_12::test_annual_cap_exceeded_at_approve`: the 2027 clock move reset the calendar-year accumulator (PRD scopes accumulators to the current calendar year), so no breach could fire; hires now dated 2026-01-01 (retention due 2026-06-30) with the sweep unmoved at 2026-08-01, keeping the scenario inside the 2026 window.

**Fixes applied to `implementation/`:**
- `services.py::forfeit_milestone` and the sweep clawback leg (`run_sweep`): the retention-share release was derived as `uplift_spent_cents − hire_share`, which under-releases when the hire share was already released (double-release). Both paths now release the milestone-kind's own corresponding earned share (hire share for HIRE, retention share for RETENTION) per PRD §3.6 "the corresponding earned campaign share" / §3.5 "the retention uplift share is released", clamped against current `spent_cents`.

## Step 8: Finalize PRD — 2026-08-15T05:47:41.148Z

The diff is exactly the three intended edits plus the one-word re-anchor. Task complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1965_employee_referral_program_administration/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 381 → PRD_FINALIZED.md 383 (+2 lines, +0.52%).

### Changes (3 edits, all traced to step_7_diff items)

- **§2.5 — insert** — Added a paragraph pinning the uniform timestamp serialization convention: every timestamp the server serializes in a response (`created_at`, `updated_at`, `api_request_timestamp`, the clock capability's `now_iso8601`, and every entity date/clock-derived field such as `submitted_at`, `cooldown_until`, `retention_due_at`, `clawback_until`, `last_terminal_outcome_at`, `earned_at`, etc.) is rendered ISO 8601 UTC with exactly three fractional digits (e.g. `2026-08-01T00:00:00.000Z`); absent values render as null. Also re-anchored the following sentence ("this convention" → "this common-field convention") so the ReferralEvent exception cannot be misread as excepting the format. — `implementation/util.py:20-27` (`iso()`), all serializers in `implementation/views.py`, `implementation/routes/ops.py:19`.
- **§3.5 — revise** — Clawback paragraph: replaced "the referrer's annual accumulators subtract the milestone's `amount_cents` for the current calendar year" (which admitted a net-0 side-effect reading diverging from the status-set formula) with wording pinning the status-lens mechanics: the milestone ceases to be summed as `PAID` and is instead subtracted as `CLAWED_BACK`, per the accumulator definitions that follow. — `implementation/services.py:154-175` (`annual_accumulators`), `implementation/services.py:600-621` (sweep clawback leg mutates only status).
- **§3.6 — revise** — Manual-forfeit sentence: "the corresponding earned campaign share" → "the corresponding earned campaign share — the hire uplift share for a `HIRE` milestone, the retention uplift share for a `RETENTION` milestone —". — `implementation/services.py:408-433` (`forfeit_milestone` per-kind release), `implementation/routes/milestones.py:95`.

### Pre-edit search logs (NO-NEW-MISMATCH RULE)

**Edit (a):** (a) Subject: wire format of serialized timestamps. (b) Enumerated: all 11 serializers in `views.py` (every timestamp field passes through `util.iso`); `util.py:20-32` (`iso`, `wall_iso` for both envelopes); `routes/ops.py:19` (`now_iso8601`); grep for `isoformat|strftime|iso(` across all routes confirmed no other emitters; grep of PRD confirmed the only prior format claims were §2.2 `api_request_timestamp` and §2.5 `created_at` (both already three-fractional-digit, consistent), and §2.4/§4's `2026-08-01T00:00:00Z` are instant specifications, not wire formats. (c) Wording adjustments: scoped the claim to "every timestamp the server serializes in a response" to avoid colliding with §2.4's prose notation; added an explicit null clause (impl `iso(None)` → `None`); used "for example" field lists to stay non-exhaustive (covers `prior_application_at`, `departed_at`, etc.); re-anchored the ReferralEvent sentence to prevent the new paragraph from capturing its "this convention" referent.

**Edit (b):** (a) Subject: accumulator effect of a PAID→CLAWED_BACK milestone. (b) Enumerated: `services.py:154-175` (sole computation — derived from current statuses at read; no stored counters); `services.py:600-621` (clawback mutates only `status`/`recovery_status`); all readers — `routes/milestones.py:60` (approve cap gate), `routes/referrals.py:182` (quote headroom), `views.py:12` (employee read); cross-checked PRD §3.1 ("defined precisely in §3.5") and §3.5's status-set formula (kept verbatim — it already matches impl). (c) Wording chosen to defer entirely to the status-lens definitions ("register the change purely through the new status") so no additive-side-effect-on-stored-counters reading survives; impl behavior (PAID→CLAWED_BACK swings the milestone's contribution from +amount to −amount) is now the unique derivable reading.

**Edit (c):** (a) Subject: which campaign share a forfeited milestone releases from `spent_cents`. (b) Enumerated every release path: `services.py:408-433` (per-kind, clamped by `campaign_release_earned:350-359`) with callers `routes/milestones.py:95` (manual, EARNED/APPROVED), `routes/employees.py:103` (termination), `services.py:444` (abuse cascade); sweep clawback `services.py:614-620` (retention share); share-creation sites `services.py:329-338` and `593-596`; PRD cross-references §3.1 ("any earned-but-now-forfeited share"), §3.7 ("earned-but-unpaid uplift shares"), §3.5 clawback ("the retention uplift share" — already per-kind, untouched). (c) No further adjustment needed: the parenthetical names the §3.4-defined shares; §3.1/§3.7 generic phrasings remain true under per-kind release; the clamp was deliberately left unpinned (§3.2's non-negativity invariant already forces the observable boundary behavior, and under-determined wording is safer).

### Items verified as needing no edit
- **`ytd_paid_gross_cents` increment point (d):** PRD §3.1 "incremented only when payment is confirmed" + §3.6 confirm-paid parenthetical already pin it; `_paid_at` is set only at `routes/batches.py:174`.
- All other step_7_diff items are pure test-fixture bugs against already-pinned PRD behavior: §3.3 steps 5–6 cap clip, §2.7 OCC-before-business ordering, §3.3 exact-instant cooldown admission, §3.5 calendar-year accumulator scoping, §3.7 abuse-cascade non-terminal gate.

## Step 9: Complete PRD — 2026-08-15T06:01:18.690Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1965_employee_referral_program_administration/workspace/PRD_COMPLETED.md` — a pure inline patch over `PRD_FINALIZED.md` (no new sections, no restructure).

## Stats

- Source `PRD_FINALIZED.md`: 383 lines, 68,916 chars → `PRD_COMPLETED.md`: 383 lines, 73,085 chars; char-delta **+4,144** (24 line-pairs touched, 27 discrete edits).
- Counts: **22 ambiguity-pins** (PRD silent), **5 mismatch-revisions** (PRD described different behavior than impl).

## Changes (section — insert|revise — ambiguity|mismatch — what — impl ref)

- §2.1 — insert — ambiguity — Employee read-scoping pinned concretely: referral list filtered, per-employee list and single-referral read 403 cross-access, and the per-referral **milestones/events subviews are NOT ownership-scoped** — `implementation/routes/referrals.py:253-271` (no ownership check) vs `:248-249` (check on get).
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` 400 — `implementation/util.py:159-184`.
- §2.3 — insert — ambiguity — list ties at the same logical instant broken by insertion order — `implementation/services.py:114-115` (`_seq`).
- §2.5 — insert — ambiguity — `version` starts at 1 and increments at most once per resource per request — `implementation/services.py:88-111` (`new_entity`, `touch` dirty-set).
- §2.10 step 6 — insert — ambiguity — body-referenced resource ids also 404 at the existence step, with the batch-milestone-add exception carved out — `implementation/routes/referrals.py:73-86`, `routes/campaigns.py:60-61`, `routes/abuse.py:39-42`.
- §2.11 — insert — ambiguity — `SUBMIT` event's `from_state` is null — `implementation/routes/referrals.py:214`.
- §3.1 — insert — ambiguity — duplicate `employee_number` → `ERR_INVALID_REQUEST` 400 — `implementation/routes/employees.py:45-47`.
- §3.1 — insert — ambiguity — tax-profile verify: missing profile → 404, non-`SUBMITTED` → `ERR_INVALID_STATE` 409 — `implementation/routes/employees.py:166-171`.
- §3.2 — insert — ambiguity — duplicate `req_number` → `ERR_INVALID_REQUEST` 400 — `implementation/routes/requisitions.py:60-62`.
- §3.2 — revise — mismatch — cancel cascade hits only pre-hire referrals (`SUBMITTED`…`OFFER_EXTENDED`; `HIRED` unaffected), not "every non-terminal referral"; cascade events record the cancelling TalentAdmin as actor — `implementation/services.py:454-463` + `routes/requisitions.py:132`.
- §3.2 — revise — mismatch — `REQ_FILLED` cascade likewise limited to pre-hire states, events recorded under actor `system` — `implementation/services.py:487-488`.
- §3.2 — insert — ambiguity — future-dated policy activation → `ERR_INVALID_STATE` 409 — `implementation/routes/policies.py:102-104`.
- §3.3 — insert — ambiguity — both `candidate_id`+`candidate_email` supplied → `candidate_id` wins; unmatched email path requires `candidate_full_name` (else 400) — `implementation/routes/referrals.py:83-103`.
- §3.3 — revise — mismatch — candidate moves to `IN_PROCESS` from `AVAILABLE` **or `DEPARTED`**; return-to-`AVAILABLE` (with `last_terminal_outcome_at` re-stamp) happens only while `IN_PROCESS` — a `HIRED`/`DEPARTED` candidate keeps that status when their referral terminates — `implementation/routes/referrals.py:210-212`, `services.py:381-393`.
- §3.3 — revise — ambiguity — `cooldown_until` recomputed on every read from the **currently ACTIVE** policy's `duplicate_cooldown_months` (default 6 when none active) — `implementation/services.py:196-205`.
- §3.3 step 7 — insert — ambiguity — tenure check is vacuous when no policy is ACTIVE (failure surfaces at step 10) — `implementation/routes/referrals.py:140-143`.
- §3.3 step 2 — insert — ambiguity — a covering campaign whose attachments already number `max_payouts` is treated as absent (unattached submission, null `campaign_id`) — `implementation/routes/referrals.py:171-176`.
- §3.3 step 3 — insert — ambiguity — granted uplift floored at zero — `implementation/routes/referrals.py:181`.
- §3.3 step 4 — revise — mismatch — zero-uplift attachment generalized: attaches with `campaign_uplift_cents` 0 for *any* zero outcome, not only zero remaining budget — `implementation/routes/referrals.py:178-181,190`.
- §3.3 — revise — ambiguity — duplicate-ring window is closed at both ends (`[now−90d, now]`) — `implementation/services.py:287-292`.
- §3.4 — insert — ambiguity — advance: invalid from/to pair → `ERR_INVALID_STATE`; valid pair but wrong role → `ERR_FORBIDDEN`, checked after pair legality — `implementation/routes/referrals.py:375-381`.
- §3.4 — insert — ambiguity — not-selected: wrong role for the current state → `ERR_FORBIDDEN` after the state check — `implementation/routes/referrals.py:436-442`.
- §3.6 — insert — ambiguity — milestone-add verifies the body-named milestone's existence only after stale-version and batch-open checks; milestone-remove validates the path milestone per §2.9 and rejects a milestone not attached to this batch with `ERR_MILESTONE_NOT_BATCHABLE` — `implementation/routes/batches.py:84-103,118-132`.
- §3.6 — insert — ambiguity — confirm-paid clears `payroll_batch_id` on `PAID` milestones; recovery lines keep the link with `recovery_status` `RECOVERED` — `implementation/routes/batches.py:172-179`.
- §3.7 — insert — ambiguity — abuse-confirm `FORFEIT` event is recorded with actor `system` — `implementation/routes/abuse.py:115`.
- §3.8 — insert — ambiguity — each group carries a `group` key; `CAMPAIGN` keys are `ATTACHED`/`NOT_ATTACHED` — `implementation/routes/analytics.py:62-67`.
- §3.8 — revise — mismatch — `hires` = referrals that ever reached `HIRED` via recorded `hire_date`, so abuse-`FORFEITED` referrals count too — `implementation/routes/analytics.py:74-76`.
- §3.8 — insert — ambiguity — groups sorted by key ascending; missing `group_by` or unparseable window bounds → `ERR_INVALID_REQUEST` 400 — `implementation/routes/analytics.py:27-43,84`.
- §4 — insert — ambiguity — subordinate list views (requisition referrals/campaigns, candidate referrals, employee referrals/abuse-cases) accept a `status` filter — `implementation/routes/requisitions.py:141,155`, `routes/candidates.py:82`, `routes/employees.py:201,215`.

Everything else in the impl (envelope shapes, clock semantics, gauntlet order and error codes, quote math, withholding variants, sweep rules and tallies, RBAC table, error catalogue) matched the PRD uniquely and was left untouched.
