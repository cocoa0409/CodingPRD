# Worklog — task_1454_retirement_plan_audit_form_5500

## Step 1: Create Task Directory — 2026-08-13T08:37:00.000Z

Pre-assigned directory `tasks/task_1454_retirement_plan_audit_form_5500/` with `workspace/` subdirectory verified to exist. No index scan performed (per pipeline instructions).

## Step 2: Generate Scaffold — 2026-08-13T09:49:00.000Z

Scaffold generation complete. All three artifacts written to `/home/ubuntu/github/CodingPRD/tasks/task_1454_retirement_plan_audit_form_5500/` and `scaffold_lint.py` reports a clean verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Artifact counts**
- `SCAFFOLD.yaml` — 13 entities, 11 state machines, 11 calculations, 9 ordered validation priority tiers, 75 endpoints, 31 error codes, 6 roles, 2 OCC concurrency rules
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 18 instances (9 rules × 2), all with structured `setup_api_calls`/`trigger`/`assert` chains
- `SCAFFOLD_CORNER_DESIGN.yaml` — 54 instances (47 active + 7 `excluded_because` stubs) across all 9 claim-guide sections; 72 instance names unique across both files; 495 calls lint-checked

**Key design decisions (harder-than-expert calibration)**
- **Archetype**: compliance/audit primary + ledger-reconciliation secondary; flat topology, cyclic state-machine shape, segregation-of-duties role model (proposer≠approver on corrective actions; filing creator≠mark_ready approver, enforced via tracked `X-User-ID`).
- **Dual-variant calcs in different domains**: participant-count STANDARD vs 80-120 election (110-participant census → H+audit vs I+no-audit, and remittance standard 3 vs 7 days); VFCP 8% vs EPCRS 5% lost-earnings (pinned literals 3288c vs 2055c, verified by executing the formulas in Python).
- **Combinatorial modes (a) and (b)**: ADP test with nested `max(1.25×, min(2×, +2))` hitting an exact 3.60==3.60 PASS boundary; lost earnings pinned to round-per-segment-then-sum (657c) vs sum-then-round (658c) — a deliberate one-cent divergence.
- **Non-linear machines on different entities**: Form5500Filing (REJECTED→DRAFT reopen loop + ACCEPTED→AMENDED_DRAFT amendment cycle) and Contribution (independent `match_status` × `timeliness_status` parallel dimensions).
- **Depth-4 transitive cascades from two triggers**: assessment-confirm → auto-finding → posture BLOCKED → READY filing auto-reverts; test-finalize FAIL → same chain from a different trigger.
- **Priority conflicts in different category pairs**: state vs business_fiscal (re-execute of a VERIFIED action) and business_safety vs business_referential (missing IQPA report beats missing DFVCP filing on a late submit).
- **Boundary precision on different metrics/endpoints**: exactly-100 participant audit threshold (recompute endpoint) and exactly-7-business-day safe harbor (late-deposit-scan endpoint), plus corner boundaries at $5,000.00 Schedule C reportability and 70.00% coverage ratio.
- **Temporal overlap with different interval semantics**: half-open plan-year intervals per (EIN, plan number) vs closed-interval trust-statement periods with +1-day adjacency.
- **Compensating invariants on different quantities**: match/unmatch conserves the reconciliation identity; execute/void of a corrective distribution restores `account_balance_cents` exactly (100000 → 95000 → 100000).
- **Determinism**: logical clock endpoint with the mandatory `2026-08-01T00:00:00Z` default; all deadline math (7-month due date, weekend roll-forward — 2026-01-31 Saturday → 2026-02-02 Monday — +2.5-month extension to the 15th, DFVCP $10/day penalty with plan-size caps) is clock-driven and pre-computed; business-day counting is weekends-only; OCC version inputs are always `${var}` captures.

One notable fix during self-review: `ERR_EXTENSION_EXPIRED` was given a reachable trigger (Form 5558 must be filed by the original due date), two corner instances were clock-pinned to respect it, and the unproduced `VOID` extension enum value was removed for enum closure.

## Step 3: Copy Shared Files — 2026-08-13T09:50:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1454_retirement_plan_audit_form_5500/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T10:05:00.000Z

75 scaffold endpoints, 75 §4 rows — exact match. The PRD is complete and all three hard contracts pass.

## Summary

Generated `/home/ubuntu/github/CodingPRD/tasks/task_1454_retirement_plan_audit_form_5500/workspace/PRD.md` from the scaffold (I did not read `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`).

**PRD line count:** 356 lines.

**Section structure:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 10 subsections (2.1 RBAC, 2.2 API Response Structure [verbatim], 2.3 Pagination, 2.4 Common Properties/Version, 2.5 Monetary & Precision, 2.6 Nested/Cross-Ref Validation, 2.7 Segregation of Duties, 2.8 OCC, 2.9 Engagement Posture Aggregate, 2.10 Logical Clock)
- §3 Business Logic & Workflows — 11 subsections organized by lifecycle-timeline (engagement setup → participant count → census → contributions/reconciliation/late-scan → testing → findings → corrective actions → schedules/fees/assembly → deadlines/extensions/submission/amendments → correction-program filings → completion)
- §4 Endpoint Definitions (75 rows, exactly 4 columns)
- §5 Error Code Catalogue (31 rows, 2 columns)

**Coverage audit (all three hard contracts PASS):**
- **Contract 1 — Field-Name Coverage: PASS.** 111 required identifiers (all entity fields + endpoint request_body/query/path params); 0 missing. Verified via split-on-backtick extraction (the regex approach mispaired on this doc; split is unambiguous).
- **Contract 2 — Rule Coverage: PASS.** All 31 error IDs appear in prose; both OCC rules expressed with `write_endpoint` + `expected_<parent>_version` + exact `error_id` (ERR_STALE_ENGAGEMENT_VERSION/412, ERR_STALE_FILING_VERSION/412); all 52 state transitions, all 11 calculations, and the validation priority orderings are in prose. Spot-verified the pinned rules: completion-guard ordering (findings sweep before filing check → ERR_OPEN_FINDINGS_REMAIN precedence), ADP→ACP pinned evaluation order, lost-earnings round-per-segment-then-sum, the 3-link posture→BLOCKED→READY_TO_FILE→SCHEDULES_COMPLETE cascade (surfaced at all three trigger points: unmatch, assessment-confirm, test-finalize), filing-submit precondition order, excise-tax 2.5-month window, and the >10-day severity hint.
- **Contract 3 — §3 Path Purity: PASS.** 780 backticked tokens in §3; 0 leading-`/`, 0 bare HTTP methods, 0 method+path combos. All endpoints referenced via state-transition framing / role+verb / capability description.

**Structural precision confirmed:** §2.2 is byte-identical to the fixed source (canonical placeholders intact); §4 4-column and §5 2-column table shapes hold; 75 scaffold endpoints map to 75 §4 rows with no omissions; all enum state/category values present as exact backticked strings.

One audit note: my enum extractor flagged a token `10` as "missing" — that is the numeric literal from the `severity_hint` threshold (`business_days_late > 10`), not an enum value; it correctly appears in prose as a number, so it is a false positive in the extraction script, not a gap.

## Step 5: Generate Unit Tests — 2026-08-13T10:55:00.000Z

Done. Summary of the generated test infrastructure for `task_1454_retirement_plan_audit_form_5500`:

## Files created

**`test_helpers/` (Stage 1, 9 files):**
- `types.py` — 30+ status/field enums + 13 entity TypedDicts (all entities carry `id`/`created_at`/`updated_at`/`version` per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (60+ methods, incl. `/_clock/set_current_utc`)
- `api_errors.py` — `ApiErrorId` enum (31 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions + `assert_reconciliation_identity` (signed unreconciled = reported − matched − adjustment)
- `factories.py` — payload factories with auto-incrementing plan numbers to avoid `(sponsor_ein, plan_number)` collisions
- `constants.py` — PRD thresholds (100-count audit threshold, 7/3-day remittance, 8%/5% earnings rates, 500000c Schedule C threshold, DFVCP 1000c/day + caps, 70.00 coverage ratio)
- `test_users.py` — opaque-role headers on stable per-duty-lane operator ids (sponsor `u-sponsor-1` vs manager `u-manager-1`) so SoD pairs pass; `make_*_headers` builders for same-id SoD attacks
- `fixtures.py` — composite chains: `create_small_plan_engagement`, `walk_to_report_issued`, `create_filing_ready_to_file`, `create_accepted_filing`, `create_late_assessment`, `setup_confirmed_late_deposit`, `setup_executed_action`, `run_test` (OCC version fetched fresh), census-group builders
- `__init__.py` — barrel export

**`test_suite/` (Stage 2):** `conftest.py` + 8 files, **81 tests**, organized simple→complex: `01_engagement_lifecycle`, `02_census_and_participant_count`, `03_contributions_and_trust`, `04_nondiscrimination_testing`, `05_findings_and_corrective_actions`, `06_filing_assembly_and_schedules`, `07_deadlines_extensions_and_submission`, `08_programs_security_and_validation`.

## Coverage audit (automated)
- **Queue A (difficulty):** 17 of 18 instances covered with exactly 2 tests each (34 tests). All tags resolve.
- **Queue B (corner):** 46 of 47 non-stub instances covered (47 tests; `dfvcp_penalty_per_day_and_cap` gets a second boundary test for filing-on-the-due-date). All 7 `excluded_because` stubs correctly untranslated; one stub (`error_stale_engagement_version_covered`) has a mislabeled pointer (`optimistic_concurrency/…` is not a §1.8 rule_id) but its catalog entry is covered by the emitted corner OCC test.
- All 81 docstrings pass the verbatim-grep check against PRD.md (whitespace-normalized, 8-word windows) and the C4 single-`Design:`-last-line check. `pytest --collect-only` collects 81 tests cleanly.

## Skipped instances (PRD-first filter)
1. **`Difficulty/priority_pair_validation_conflict/execute_verified_action_state_beats_fiscal`** — the instance's claim is that `ERR_INVALID_STATE_TRANSITION` (state) beats `ERR_DISTRIBUTION_EXCEEDS_BALANCE` (fiscal) on a re-executed VERIFIED action. PRD §3.7 states both rules but never pins their evaluation order (unlike submit, where §3.9 explicitly says "evaluated in the order given here"). Silence pattern: validation-priority. The fiscal rule itself remains covered by the corner instance `distribution_exceeding_balance_rejected` in an isolated scenario.
2. **`Corner/endpoints/findings_list_filter_by_status`** — PRD §2.3 specifies only pagination query params (`limit`/`offset`); it never states that list endpoints honor `status=`/`engagement_id=` filters. A PRD-only implementer could ignore unknown query params and fail the assertion. (Setup chains elsewhere in the suite remain safe because fresh-DB tests contain exactly one engagement, making filter params non-load-bearing.)

## Notable decisions
- **Second tests per difficulty instance** exercise a genuinely different facet rather than duplicating: e.g. ADP min/max is tested in both the 2×-multiplier branch (recipe's 1.80→3.60) and the 1.25× aggregate branch (12.00→15.00); per-segment rounding is tested in both divergence directions (657-vs-658 and 1206-vs-1205, verified arithmetic); the confirm cascade is tested at HIGH (BLOCKED + filing revert) and MEDIUM (AT_RISK, filing stays READY_TO_FILE).
- **Version assertions are relative** (`v0 + N`, with `v0` captured at creation) because PRD §2.4 pins the increment but not the initial value.
- **`engagement_computed_fields_input_ignored` was emitted** per established benchmark convention (sibling task 1276 emits the same pattern): PRD §3.1 verbatim-pins the created state (`DRAFT`/`ON_TRACK`/null computed fields), which the test asserts even with polluted input.
- OCC test-result creates always fetch the engagement version fresh via `current_engagement_version()`, since creates bump the engagement version per PRD §3.5.

## Step 6: Generate Implementation — 2026-08-13T10:55:00.000Z

All verification passes. The implementation is complete.

## Summary

**Files created** in `/home/ubuntu/github/CodingPRD/tasks/task_1454_retirement_plan_audit_form_5500/workspace/implementation/`:

| File | Role |
|---|---|
| `start.sh` | Foreground launcher; guards `pip install` behind an `import flask` check; `exec python3 app.py` |
| `requirements.txt` | flask>=3.0 |
| `app.py` | Flask entry, error handlers (ApiError → catalog envelope; 404/405 → `ERR_NOT_FOUND`), binds `0.0.0.0:$PORT` (default 10000) |
| `store.py` | In-memory dicts (13 stores), logical clock pinned to `2026-08-01T00:00:00Z` at boot, strictly-increasing 3-fractional-digit timestamps, `version`/`updated_at` touch helper |
| `errors.py` | Full error catalog with scaffold-exact IDs and HTTP statuses |
| `envelope.py` | Success/error envelopes: `meta.api_request_id` (`req_…`), `meta.api_request_timestamp`, `response_type` object/array/error, pagination fields in `meta` |
| `auth.py` | `X-User-ID`/`X-User-Role` validation (400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), role gating (403 `ERR_FORBIDDEN_FOR_ROLE`), store lock + time-rules sweep per request |
| `dates.py` | Business-day counting, weekend roll-forward, month arithmetic |
| `validate.py` | Required-field/enum/int/bool/date validation (400), `limit`/`offset` parsing (1–100 / ≥0) |
| `domain.py` | All calculations and cross-entity cascades |
| `routes_*.py` | 5 route modules + clock |

**Endpoints: 75 total**, matching the scaffold §1.5 table exactly (14 engagement, 5 participant, 5 contribution, 5 trust-statement, 4 test-result, 4 assessment, 6 finding, 7 corrective-action, 3 fee, 3 filing + 6 filing actions, 4 schedule-entry, 3 extension, 5 correction-program, 1 clock).

**Organization of the hard parts:**
- *State machines* — implemented per entity in its route module with precondition → side-effect ordering from the scaffold (e.g., complete() evaluates the findings sweep before the filing check; submit() follows the pinned 4-step order: REPORT_ISSUED → audit report → deadline → DFVCP).
- *Calculations* — `domain.py` with `Decimal` round-half-up everywhere: per-segment round-then-sum VFCP/EPCRS lost earnings (8%/5%, 365 basis), ADP/ACP with 4dp ADR → 2dp means → nested min/max limits, leveling with ties broken by `created_at` then `external_ref`, and the pinned **ACP-consumes-post-refund-ADP-figures** order (stored `_refunds` per failed ADP result). Verified numerically (e.g., HCE 7.00 vs NHCE 3.33 → max_allowed 5.33, FAIL).
- *Validation priority* — auth (1–2) → body/malformed (400) → existence left-to-right (404, cross-engagement FK = 404) → state (409) → business safety/temporal/referential/constraint/fiscal (422/409 per catalog), with the PRD-specific override that a wrong-engagement trust statement at match time returns `ERR_STATEMENT_PERIOD_MISMATCH` (422).
- *Cascades* — posture aggregate recomputed on every finding/test/statement/filing mutation and clock set; entering BLOCKED reverts READY_TO_FILE filings; unmatch reverts RECONCILED→DISCREPANCY; execute cascades to assessment CORRECTED + timeliness CORRECTED + finding auto-CORRECT; void of EXECUTED reverses the balance exactly (recompute excludes VOIDED) and reopens the finding without reverting the assessment.
- *OCC* — `expected_engagement_version` on test-result create (412 `ERR_STALE_ENGAGEMENT_VERSION`), `expected_filing_version` on amendments (412 `ERR_STALE_FILING_VERSION`, checked before the ACCEPTED-state check per PRD sentence order).
- *Time rules* — extension EXPIRED sweep + posture deadline-arm re-evaluation on clock set and lazily on every request; `effective_due_date`/`has_active_extension` refreshed on filing reads.

**No seeding**: the store starts empty (verified — fresh boot returns `data: []`, `total_count: 0`); no files are written anywhere; `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, and `test_helpers/` were never read.

**Boot verification**: launched fresh via `bash start.sh` on multiple ports across separate processes; probed successfully each time. Three smoke suites (75+ behavioral assertions covering auth envelope, plan-year overlap/adjacency, 80-120 election divergence, bulk import atomicity, match/unmatch/reconcile/resolve, late-deposit scan classification, assessment→finding auto-creation, SoD on approve, excise tax, void reversal, REJECT: handling, extension grant/expiry/fallback, DFVCP penalty (15 days × 1000 = 15000 with the 75000 Schedule-I cap), schedule completeness gates, amendment OCC, correction-program guard, certified-statement gapless coverage, and pagination) all pass on fresh boots.

## Step 7: Run Tests and Iterate — 2026-08-13T11:05:00.000Z

Clean 8-round parallel sweep achieved: **81/81 passed in every round (rounds 1–8), 0 failures.**

## Summary

**Iterations run:** 2 sweeps (16 rounds total). Sweep 1 surfaced a single consistent failure (8/8 rounds); sweep 2 after the fix was fully green.

**Failing test diagnosed (union across sweep 1):**
- `test_04_nondiscrimination_testing.py::TestFinalizeCascade::test_fail_finalize_creates_finding_blocks_and_reverts_filing` — failed in all 8 rounds with `Setup step failed with HTTP 409: ERR_SCHEDULE_INCOMPLETE - Required schedule type (uncomputed) has no entries`.

**Diagnosis (per protocol):** STEP 1a passed — the test's assertions (FAIL-finalize auto-creates OPEN/HIGH `TEST_FAILURE_AUTO` finding → posture `BLOCKED` → `READY_TO_FILE` filing reverts to `SCHEDULES_COMPLETE`) are verbatim-covered by PRD §3.5/§2.9. The failure was confined to the *setup*: `_setup_failing_adp_with_ready_filing` built a READY_TO_FILE filing on an engagement whose participant count was never recomputed, leaving `required_schedule_type` null (PRD §3.1). PRD §3.8 defines the required schedule set only through that computed field and is silent on the null case — the two-reader experiment diverges (skip-null vs unsatisfiable-null, the latter being the implementation's reading), so the setup depended on PRD-silent behavior. STEP 2 verdict: test-setup bug, not an implementation bug.

**Tests deleted:** none.

**Fixes applied to `test_suite/`** (1 file):
- `/home/ubuntu/github/CodingPRD/tasks/task_1454_retirement_plan_audit_form_5500/test_suite/test_04_nondiscrimination_testing.py` — in `TestFinalizeCascade._setup_failing_adp_with_ready_filing`, added `recompute_count(eng["id"])` (and its import) before `create_filing_ready_to_file(...)`. With 4 eligible ACTIVE participants and the standard rule (`use_80120_election` false), `required_schedule_type` is deterministically `"I"` under both PRD readings, so `mark_schedules_complete` no longer depends on the PRD-silent null case. The test's PRD-verbatim assertions are unchanged.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful; no check was weakened or added.

## Step 8: Finalize PRD — 2026-08-13T11:12:00.000Z

The task is complete. `/home/ubuntu/github/CodingPRD/tasks/task_1454_retirement_plan_audit_form_5500/workspace/PRD_FINALIZED.md` is written with exactly one intra-paragraph edit.

**Line counts and delta**
- PRD.md: 356 lines; PRD_FINALIZED.md: 356 lines — 0 line delta (the single change is an in-place expansion of one sentence inside the §3.8 paragraph on line 214).

**Changes**
- §3.8 — revise — extended the `ERR_SCHEDULE_INCOMPLETE` sentence with a parenthetical pinning that a null `required_schedule_type` (participant count never recomputed, §3.1) remains an unsatisfiable member of the required schedule set, so mark-schedules-complete rejects with `ERR_SCHEDULE_INCOMPLETE` (HTTP 409) — `implementation/routes_filings.py:173-184` (`_required_schedule_types` appends a `None` "unsatisfiable member") and `implementation/routes_filings.py:196-199` (presence loop raises `ERR_SCHEDULE_INCOMPLETE`, message `"Required schedule type (uncomputed) has no entries"`).

**Per-edit pre-edit search log**

Edit 1 (the only edit):
- (a) Subject: membership and satisfiability of the required schedule set at the mark-schedules-complete step when `required_schedule_type` is null.
- (b) Impl paths enumerated (grep for `required_schedule_type`, `_required_schedule_types`, `ERR_SCHEDULE_INCOMPLETE`, `mark_schedules_complete` across all `implementation/*.py`, then read of `routes_filings.py`, `routes_engagements.py`, `domain.py`):
  - `routes_engagements.py:75` — creation sets `required_schedule_type: None` (source of the null case; §3.1 already pins null-until-recompute).
  - `routes_engagements.py:207-216` + `domain.py:205-224` — the only writer making it non-null; always `'H'`/`'I'` afterward, never re-nulled.
  - `routes_filings.py:173-184` — sole builder of the required set; null (or missing engagement, unreachable: filings require an existing engagement at `routes_filings.py:121-123` and no delete endpoint exists) appends `None`; `'C'`/`'A'` members independent of the count.
  - `routes_filings.py:187-207` — sole consumer; presence check runs before the verification check, so the null member always surfaces `ERR_SCHEDULE_INCOMPLETE`, never `ERR_SCHEDULE_NOT_VERIFIED`.
  - `routes_filings.py:349-374` — `create_schedule_entry` restricts `schedule_type` to `('H','I','C','A')`, so no entry can ever satisfy the null member.
  - `routes_filings.py:264` — DFVCP penalty cap reads `required_schedule_type == 'I'`; different subject (penalty cap), and unreachable with null (submit requires READY_TO_FILE ⇒ a prior successful mark-schedules-complete ⇒ non-null). The wording makes no claim there.
  - Amendment cycle (`routes_filings.py:311-327` → AMENDED_DRAFT → same `mark_schedules_complete`) uses the same required-set path; the wording targets "the mark-schedules-complete step" generically, and the paragraph's existing final sentence already extends the same rules to AMENDED_DRAFT.
- (c) Wording adjustment: folded the pin into the existing `ERR_SCHEDULE_INCOMPLETE` sentence as a parenthetical rather than a standalone unconditional claim, because the filing-state guard (`ERR_INVALID_STATE`, `routes_filings.py:191-193`) precedes the presence check — scoping the pin strictly to the presence-check outcome avoids overclaiming the endpoint's error for filings in other states.

## Step 9: Complete PRD — 2026-08-13T11:40:00.000Z

Done. PRD_COMPLETED.md is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1454_retirement_plan_audit_form_5500/workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output:** PRD_FINALIZED.md 356 lines / 63,209 chars → PRD_COMPLETED.md 356 lines / 71,588 chars (char-delta **+8,311**; all edits are inline within existing paragraphs — no new sections, no new paragraphs).

**Counts:** 29 ambiguity-pins, 6 mismatch-revisions (35 edited paragraphs total).

### Mismatch revisions (PRD said X, impl does Y)
- §2.4 — revise — mismatch — posture-only recomputation no longer claimed to increment engagement `version` (impl's `recompute_posture` never calls `touch`) — implementation/domain.py:177-187, store.py:67-70.
- §2.10 — revise — mismatch — clock endpoint *sets* the clock to any instant (no monotonicity guard implied by "advances"); pinned `current_utc` format as second-precision UTC — implementation/routes_clock.py:14-25.
- §3.4 — revise — mismatch — certification guard: dropped "with a gap note" (no note is persisted) and "remains in DISCREPANCY" → "the reconcile moves the statement to DISCREPANCY" (applies from IMPORTED too) — implementation/routes_contributions.py:246-254.
- §3.5 — revise — mismatch — `testing_method` is accepted and stored on every test result (including COVERAGE_410B), meaningful only for ADP/ACP — implementation/routes_testing.py:71,87.
- §3.5 — revise — mismatch — `issue_report` rejects when *any* engagement test result is COMPUTED (not only "current-official" ones), and also requires non-null `participant_count_beginning` (ERR_PARTICIPANT_COUNT_REQUIRED, checked after the FIELDWORK check) — implementation/routes_engagements.py:155-163.
- §3.7 — revise — mismatch — excise window is "two months and fifteen days after the last day of the plan year" (2026-03-15 for PY2025), strictly-later comparison, 10% rounded half-up — implementation/domain.py:400-403, routes_testing.py:459-464.

### Ambiguity pins (PRD silent, pinned to impl)
- §2.1 — insert — unrecognized role string → ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER 400; 403 only for recognized-but-disallowed roles — auth.py:25-30.
- §2.3 — insert — invalid limit/offset → ERR_INVALID_REQUEST 400; list endpoints accept exact-match query filters; boolean filters accept only true/false — validate.py:102-134.
- §2.6 — insert — field-level validation failures (missing/wrong-type/out-of-range/malformed) → ERR_INVALID_REQUEST 400 — validate.py:8-99.
- §3.1 — insert — plan_year_end ≤ plan_year_start → ERR_INVALID_REQUEST 400 — routes_engagements.py:53-54.
- §3.2 — insert — participant-count recomputation outside DRAFT/DATA_COLLECTION/TESTING/FIELDWORK → ERR_INVALID_STATE_TRANSITION 409 — routes_engagements.py:211-213.
- §3.3 — insert — census cent fields must be integers ≥ 0 — routes_participants.py:40-42.
- §3.3 — insert — bulk-import count ≥ 1, template may carry status (default ACTIVE), 201 array response — routes_participants.py:87-109.
- §3.4 — insert — new contribution's trust_statement_id/business_days_elapsed null — routes_contributions.py:67-68.
- §3.4 — insert — statement period_end < period_start → 400; reported_deposit_total_cents ≥ 0; initial matched=0/adjustment=0/unreconciled=reported — routes_contributions.py:165-188.
- §3.4 — insert — match guard order (UNMATCHED check → statement status → engagement/period), already-matched → 409 — routes_contributions.py:102-117.
- §3.4 — insert — unmatch of non-MATCHED → 409 — routes_contributions.py:134-135.
- §3.4 — insert — reconcile only from IMPORTED/DISCREPANCY → else 409 — routes_contributions.py:241-243.
- §3.4 — insert — resolve only from DISCREPANCY → else 409; adjustment_cents overwritten — routes_contributions.py:265-272.
- §3.4 — insert — scan response is 200 array of the engagement's assessments; informational lost_earnings_vfcp_cents uses the logical clock date at scan time as correction date — routes_engagements.py:248-261.
- §3.4 — insert — confirm/dismiss only from ASSESSED → else 409; LATE_DEPOSIT_AUTO finding description fixed text — routes_testing.py:176-199, domain.py:415-417.
- §3.5 — insert — new test result has is_current_official false; computation not gated on engagement status — routes_testing.py:83-101.
- §3.5 — insert — ADP/ACP empty NHCE/HCE group → ERR_INVALID_REQUEST 400 — domain.py:283-285.
- §3.5 — insert — ACP consumes the most recently computed failed ADP result's refunds; correction_deadline set on every result — domain.py:257-275, routes_testing.py:94.
- §3.5 — insert — finalize non-COMPUTED → 409; TEST_FAILURE_AUTO finding links test_result_id, fixed description — routes_testing.py:131-147.
- §3.6 — insert — acknowledge non-OPEN → 409; waive only from OPEN/ACKNOWLEDGED → 409, guard order status→severity→justification, ACKNOWLEDGED waive needs no justification — routes_testing.py:265-293.
- §3.7 — insert — proposal guard order (resolution → reference presence/scope → finding status → assessment-CONFIRMED); missing references → 400, unresolvable → 404 — routes_testing.py:327-356.
- §3.7 — insert — negative earnings segments contribute zero days — domain.py:233-236.
- §3.7 — insert — excise_tax_cents 0 at proposal and for non-distribution types — routes_testing.py:373.
- §3.7 — insert — approve/execute/verify wrong-status → 409; every void requires non-empty reason; PROPOSED void without `REJECT:` → 409 — routes_testing.py:410-512.
- §3.7 — insert — deposit actions credit by total_amount_cents; LED affects the assessment's contribution's participant; participantless QMAC has no balance effect — domain.py:75-106.
- §3.8 — insert — filing initial fields (filed_date null, is_late false, penalty_cents 0, has_active_extension false) — routes_filings.py:129-142.
- §3.8 — insert — schedule-entry amount_cents ≥ 0; payload must be object / fee-ids array (400); nonexistent fee id → 404; entries addable in any filing status — routes_filings.py:331-374.
- §3.8 — insert — fee-disclosure line_item is `C-1c <provider>`, payload carries DIRECT/INDIRECT fee ids, re-run updates in place — routes_engagements.py:288-312.
- §3.8 — insert — mark_schedules_complete / mark_ready from other statuses → 409 — routes_filings.py:191-216.
- §3.9 — insert — extension guard order: FILED/ACCEPTED → deadline-expired → existing-GRANTED — routes_filings.py:424-433.
- §3.9 — insert — record_disposition non-FILED → 409; reopen non-REJECTED → 409; amendment-cycle marker persists through rejection/reopen — routes_filings.py:268-327.
- §3.10 — insert — missing/non-array linked_finding_ids → 400; submit permitted from DRAFTED or REJECTED (same endpoint resubmits); decision from wrong status → 409 — routes_filings.py:478-557.

No remaining PRD silence or mismatch versus implementation/ was found in the walk (all endpoints, both OCC checks, posture aggregate, cascades, calculations, and error catalog cross-checked).
