# Worklog — task_2432_cash_assistance_work_participation_administration

## Step 1: Create task directory — 2026-09-02T16:11:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2432_cash_assistance_work_participation_administration` and its `workspace/` subdirectory. Index 2432 was pre-assigned by the invoker; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-02T18:47:00.000Z

NOTE (orchestrator): the first scaffold subagent invocation was terminated by an upstream API timeout after ~90 min / 133k tokens with zero files written. It was resumed via SendMessage with its context intact and an explicit incremental-write strategy (write each YAML in <=400-line chunks, validate with yaml.safe_load after each file) rather than one giant tool call. The resumed run completed successfully. Verbatim summary follows.

All three scaffold artifacts are complete, parse, and pass the linter.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2432_cash_assistance_work_participation_administration/`)

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys): **15 entities** (Household, Application, IncomeSource, ResourceItem, AssistanceCase, TimeLimitMonth, TimeLimitExtension, WorkAssignment, ParticipationReport, ComplianceEpisode, SupportiveServiceAuthorization, DiversionGrant, Overpayment, RecoveryTransaction, FederalReportingPeriod), **10 state-machine blocks**, **15 calculations** (incl. the pinned `constants` block), **31 validation-ladder rules**, **65 endpoints**, **51 error ids**, **3 OCC concurrency rules**, **7 roles**. `api_prefix: ""`, difficulty `beyond_expert`, topology `flat`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`, complexity layers `[rate_threshold_triggers, cascading_side_effects, dual_variant_calculation, optimistic_concurrency]`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`: **9 rules / 29 instances** (3,3,3,3,4,4,3,3,3), every instance with a full structured `setup_api_calls` + `trigger` + `assert` recipe.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`: **9 sections / 56 instances = 43 full recipes + 13 `excluded_because` stubs** — entities 11, state_machines 9, calculations 9, validations 9, endpoints 4, errors 3, rbac 4, cross_cutting_complexity_layers 6, consistency_model 1.

**Lint verdict** (`scaffold_lint.py` on the task dir):
```
  §1.5 endpoints declared:    65
  §1.1 entities declared:     15
  §1.8 instances scanned:     29
  §1.9 instances scanned:     43
  Calls scanned (§1.8+§1.9):  709

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Independent audits also pass: all 13 stub `difficulty_instance` citations resolve by name into the difficulty file, no stub carries a `test_recipe`, no name collides across the two design files, and every uppercase token in the corner file is either a declared enum/constant or intentionally free text (`CANYON` county code, prose reasons, and the deliberately invalid `budgeting_method: MONTHLY_AVERAGE`).

**Key design adjudications**

- **Two-dimensional case state.** `AssistanceCase` carries independent `benefit_status` (PENDING_ISSUANCE/ACTIVE/SUSPENDED/CLOSED) and `compliance_status` (NOT_REQUIRED/EXEMPT/ASSIGNED/CONCILIATION_PENDING/SANCTIONED/CURE_PENDING); suspension keys on `sanction_level == 2`, full-family closure on `== 3`. That split is what makes `non_linear_state_machine` and the cross-entity-dependency instances non-trivial.
- **Dual-variant pairs chosen for §0.5 rule 1:** prospective vs retrospective budgeting, state (24-month) vs federal (60-month) clock, and GROSS vs NET overpayment establishment — three different entity domains.
- **Deterministic time.** A single `POST /_clock/set_current_utc` test endpoint (last rung of the §1.5 ladder, clock starts 2026-08-01T00:00:00Z) is the only source of "now"; it drives conciliation deadlines, `sanction_imposed_month`, and the current federal fiscal year used by `AssistanceCase.supportive_fy_authorized_cents`. No wall-clock waits anywhere.
- **Deliberately mismatched interval semantics** so overlap reasoning cannot be copy-pasted: supportive-service periods are closed-inclusive (shared endpoints collide), work-assignment ranges are half-open (adjacent ranges do not), and the diversion ineligibility window blocks its last covered month but not the next.
- **Conflict mechanism is OCC only** — three rules on `expected_case_version` / `expected_overpayment_version` returning 412; no concurrency vocabulary. Every guarded write is preceded by a `GET` that captures `version`, and OCC inputs are always `${var}`, never literals.
- **WPR pipeline pinned to five stages with two denominators** — the caseload-reduction credit uses the *unadjusted* `D_m` while the rate uses the sanction-disregard-adjusted `A_m`; the new `rate_threshold_triggers` corner instance exploits exactly that (all three quarter months disregarded → `wpr_all 0.00`, yet `current_caseload 1.00`, credit `50.00`, adjusted target `0.00`, `target_met true`).
- **`TimeLimitMonth` has `common_fields: false`** (append-only ledger row keyed by case + benefit_month), so no recipe captures an id from it; the ledger is read through `GET /cases/{id}/time-limit-months`.
- Two FKs (`TimeLimitMonth.extension_id`, `RecoveryTransaction.reverses_transaction_id`) were dropped during generation because §1.5 could not give them reverse-reachability; the same semantics are carried by computed fields instead.
- All formula-derived assertions are author-computed literals (e.g. size-3 no-income grant 41650, level-1 sanction 31237, diversion lump sum 124950, minimum-issuance boundary at countable 47824 → 1000 vs 47825 → ERR_INELIGIBLE_ZERO_BENEFIT, self-report factor 41 → 20).

## Step 3: Copy shared files — 2026-09-02T17:43:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes). Run out of order (before Step 2 finished) since it has no dependency on the scaffold.

## Step 4: Generate PRD — 2026-09-02T19:02:00.000Z

ORCHESTRATOR TRUNCATION CHECK (per invoker's guard): independently ran `wc -l` + `tail -25` + section grep on workspace/PRD.md. 487 lines, ends on the final §5 error-catalogue row `| \`ERR_DIVERSION_REQUIRES_BENEFIT\` | 422 |` — a clean table close at a real section boundary, no mid-sentence cut. All sections §1–§5 present with §3.1–§3.10 subsections intact. NOT truncated; no regeneration needed. Doc generator was also given an incremental-write instruction (<=250 lines per tool call) as a preventative measure after Step 2's timeout.

Verbatim subagent summary follows.

All checks pass. Verification complete.

**Artifact:** `workspace/PRD.md` — **488 lines**

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Common Record Properties and the Audit Trail · 2.5 The Logical Program Clock · 2.6 Money, Percentages, Months and Rounding · 2.7 Guarding Against Stale Reads · 2.8 The Rejection Ladder · 2.9 Nested Path Resolution · 2.10 Two Independent Case Dimensions and Cascade Discipline · 2.11 Conserved Quantities
- §3 Business Logic & Workflows — 3.1 Registering the Assistance Unit and Classifying the Family · 3.2 Building the Application Record and Running the Determination · 3.3 Disposing of the Determination: Approval, Denial, Withdrawal and Diversion · 3.4 Monthly Issuance, the Two Time-Limit Clocks and Hardship Extensions · 3.5 Assigning Allowable Work Activities · 3.6 Reporting and Verifying Participation Hours · 3.7 Noncompliance: Conciliation, Good Cause, Sanction Escalation and Cure · 3.8 Supportive Services for Transportation, Child Care and Work Expenses · 3.9 Overpayments: Establishment, the Recovery Ledger and Fraud Referral · 3.10 Federal Reporting: Participation Rates and the Caseload Reduction Credit
- §4 Endpoint Definitions (65-row, 4-column table)
- §5 Error Code Catalogue (51-row, 2-column table)

**Completeness check (covered vs declared)**
| Item | Declared | Covered |
|---|---|---|
| Endpoints (path present in §4) | 65 | 65 |
| Error ids | 51 | 51 (all 51 also narrated in §3 prose, not only tabled) |
| Calculations | 15 | 15 |
| Validation rules | 31 | 31 (all 15 priority tiers of the ladder in §2.8; the only "unmatched" error ids were the scaffold's own placeholders `ERR_<RESOURCE>_NOT_FOUND` / `ERR_INVALID_<ENTITY>_STATE`, whose 12 + 10 concrete expansions are all present) |
| Constant leaf values | 61 | 61 literal values in prose |
| State-machine states | 45 | 45 |
| Enum values | 127 | 127 |

`tail -40` confirms the file ends on the final §5 row — a clean table close at a real section boundary, no truncation, no audit footer.

**Hard Contracts**

Field coverage check
- Required names (131 entity fields ∪ endpoint input/path identifiers): 140
- Present verbatim in backticks: 140
- Missing: none (first pass surfaced `overpayment_id`; appended to §3.9 and re-verified)
- Status: PASS

Rule coverage check
- 31 validations, 10 state machines (incl. the dual-dimension `benefit_status`×`compliance_status` and `status`×`fraud_referral_status` machines), 3 concurrency rules, 15 calculations incl. all 4 dual-variant ones (`countable_income_determination` PROSPECTIVE/RETROSPECTIVE, `time_limit_clock` STATE/FEDERAL, `overpayment_establishment` GROSS/NET, plus the pinned 6-step benefit calc and 5-stage WPR), and cascades A/B/C all expressed in prose
- Status: PASS

Path purity check
- §3 backticked tokens scanned: 890
- Tokens beginning `/`: 0 · bare HTTP-method tokens: 0 · method+path tokens: 0
- Unbackticked method+path or bare-path text in §3: 0
- Status: PASS

Constraint honored: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. One YAML load of `SCAFFOLD.yaml` only.

Two things worth flagging for the pipeline: (1) five scaffold preconditions declared no error code, so I pinned them consistently — diversion offer on `ONGOING_ASSISTANCE` → `ERR_INVALID_APPLICATION_STATE`; work-assignment activate outside {`ASSIGNED`,`CONCILIATION_PENDING`,`CURE_PENDING`} → `ERR_INVALID_CASE_STATE`; extension grant outside {`ACTIVE`,`SUSPENDED`} → `ERR_INVALID_CASE_STATE`; episode create outside {`ASSIGNED`,`EXEMPT`,`CURE_PENDING`} → `ERR_INVALID_CASE_STATE`; `verified_hours` outside 0..`reported_hours` → `ERR_INVALID_REQUEST`. (2) `GET /households/{id}/applications` is documented as newest-first per the scaffold, a deliberate stated exception to the §2.3 `created_at` ascending default.

## Step 5: Generate unit tests — 2026-09-02T20:35:00.000Z

Launched concurrently with Step 6 in a single assistant message (physical isolation: implementation/ generator could not read test_suite/ because it did not exist at its spawn time). Verbatim subagent summary follows.

All done. Full suite is green against the reference implementation.

## Files written

- `test_helpers/` — `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`
- `test_suite/` — `conftest.py` plus 17 test files:
  - Queue A (§1.8 difficulty): `test_01_dual_variant_calculations.py` (6), `test_02_formula_pipelines.py` (6), `test_03_state_machines.py` (6), `test_04_transitive_cascades.py` (6), `test_05_rejection_ladder.py` (8), `test_06_boundaries.py` (8), `test_07_cross_entity_state.py` (6), `test_08_temporal_overlap.py` (6), `test_09_conserved_quantities.py` (6) — **58 tests**
  - Queue B (§1.9 corner): `test_10_entities.py` (11), `test_11_lifecycles.py` (7), `test_12_calculations.py` (4), `test_13_validations.py` (8), `test_14_endpoints.py` (4), `test_15_errors_rbac.py` (4), `test_16_cross_cutting.py` (4), `test_17_consistency.py` (1) — **43 tests**

**101 tests total, 233 PRD citations.**

## Coverage against the two design indices

- Queue A: 29 difficulty instances, all translated, every one with >=2 tests. 0 skipped.
- Queue B: 56 corner instances = 43 non-stub + 13 `excluded_because` stubs. All 43 non-stub instances translated (>=1 test each); the 13 stubs were not translated, and all 13 of their `difficulty_instance` cross-references resolve to real §1.8 instances.
- Every test carries exactly one `Design:` line as the last docstring line; 0 unresolved tags, 0 untagged, 0 dual-tagged, 0 uncovered instances. No instance was skipped, weakened, or stubbed.

## Verification

- `prd-bench-local-run --isolation per-test-server` against `workspace/implementation`: **101/101 passed, 0 failed, 0 errors, 0 skipped** (results at `/tmp/results.2432.b.json`).
- First sweep surfaced 3 genuine test bugs of mine, all fixed and re-verified:
  1. `test_10_entities.py` used `county_code "CANYON"`; §3.1 pins it to exactly three uppercase letters -> `"CAN"`.
  2. `test_14_endpoints.py` pinned the clock reply to `"2026-10-01T00:00:00Z"`, but §2.4 specifies timestamps with three fractional digits (server returns `...00.000Z`) -> now asserts the instant prefix, leaving the fraction unconstrained.
  3. `test_08_temporal_overlap.py` expected the post-window application to determine at 17000 without attaching its own income sources (they are per-application) -> the same two sources are now attached to the November application, so 17000 is genuinely derived.
- Every citation survives a literal grep of `workspace/PRD.md` (`missing=0`); every file passes `py_compile`.

## Design adjudications

- **A** — Omitted the design's `WorkAssignment TERMINATED` / `CASE_CLOSED` assertions for extension-revocation-driven closure: §3.4 names only the benefit-status move for that path (cross-entity-cascade silence).
- **B** — State is re-read only through PRD-covered GET/list endpoints; only `POST /applications/{id}/approve` has its body pinned as the new case by §3.3. Create responses are otherwise treated as the created resource on the strength of the §4 `201 Created` sentence.
- **C** — Kept the four `priority_pair_validation_conflict` instances: §2.8 publishes the rejection ladder as contract, so the validation-priority silence pattern does not apply.
- **D** — Kept the level-3 void assertions: §3.5 enumerates `CASE_CLOSED` in the adverse-termination branch and §2.11 requires exact cap restoration.
- **E** — `rejecting_a_participation_report_leaves_cumulative_hours_unchanged` claims `verified_hours == null`; §3.6 zeroes all three credit fields on rejection, so the test asserts 0.
- **F** — `extension_grant_beyond_the_twelve_month_hardship_cap_is_refused`: the design's setup (12-month grant from 2026-09 with only 2026-08 issued) cannot produce the refusal, because §3.4 defines `extension_months_used` as the count of *issued* rows flagged `GRANTED_EXTENSION` — the design itself asserts it is 0. Re-based on 13 issued months (2026-08..2027-08) with a 12-month grant from 2026-08, so `extension_months_used` genuinely reaches 12 and the second grant is refused per the PRD.
- **G** — `advancing_the_clock_moves_the_current_fiscal_year_for_the_case_rollup`: the design asserts `supportive_fy_authorized_cents == 25000` after a clock move alone, but §3.8 recomputes that rollup on authorize/void, not on a clock move (computed-field silence). The test asserts 0 at authorize time under the FY2026 clock, then moves the clock and performs a second FY2027 authorize so the rollup legitimately recomputes to 55000.

## Step 6: Generate implementation — 2026-09-02T20:03:00.000Z

Launched concurrently with Step 5 in the same assistant message. Verbatim subagent summary follows.

Implementation complete for `task_2432_cash_assistance_work_participation_administration`.

## Modules written
All under `workspace/implementation/` (~2,980 lines total, every file passes `python3 -m py_compile`):

Infrastructure
- `app.py` — app factory, 9 blueprints, `ApiError`/`HTTPException`/generic error handlers, `PORT` env launch
- `store.py` — in-memory `_Db` (15 dicts), logical clock (`CLOCK_EPOCH = 2026-08-01T00:00:00Z`), `_seq` ordering counter, `new_record`/`touch`/`apply_computed`/`serialize`
- `respond.py` — `{meta, response_type, data}` envelope, `req_` + 20 uppercase alnum ids, pagination meta (default 10, max 100)
- `errors.py` — all 51 error ids with their PRD HTTP statuses
- `calc.py` — every pinned constant plus the pure calculations (6-step grant formula, both income pipelines, resource countable value, diversion figures, credited hours, participation predicate, established amount, monthly recoupment)
- `guards.py` — role/ownership/SoD guards and the declaration-order field validator
- `domain.py` — rollups and the three named cascades (shortfall->hold, sanction->suspend/close->pause recoupment, extension grant/revoke->clock flip), supportive cap waterfall, overpayment ledger recompute

Routes (`routes/`): `households.py` (4), `applications.py` (15), `cases.py` (9), `work.py` (9), `compliance.py` (8), `supportive.py` (6), `overpayments.py` (9), `reporting.py` (4), `clock.py` (1)

Plus `requirements.txt` (`flask>=3.0`) and executable `start.sh` (installs Flask only if missing, then `exec python3 app.py`).

## Endpoint coverage
**65 registered / 65 declared** in SCAFFOLD.yaml (verified by iterating `app.url_map`). Storage is process memory only — no SQLite, no disk, no seeding; `GET /cases` on a fresh boot returns an empty array.

## Boot verification
Relaunched via `bash start.sh` on a random free port (20434) as a fresh process: booted clean, `GET /cases` -> well-formed array envelope with `api_request_timestamp: 2026-08-01T00:00:00.000Z` (clock resets every boot, as required by per-test-server isolation), `GET /cases/nope` -> 404 `ERR_CASE_NOT_FOUND` envelope, `POST /households` -> 201 with derived `family_type` and all clock rollups at 0, `POST /_clock/set_current_utc` -> 200. Server then killed (only the task_2432 process; other agents' servers on the host were left alone), and `__pycache__` directories removed from the deliverable.

## Behavioural verification
Five smoke scripts (in `/tmp`, outside the deliverable) exercised: envelope/auth/ownership/SoD errors, both income pipelines including the per-source retrospective floor, the pinned grant formula, approval guard ladder, issuance ledger + 24-month closure, hardship extension grant/revoke month conservation, capacity checks, self-report credit flooring, the shortfall->episode->HELD cascade, conciliation dates and deadline gate, good cause (case -> `EXEMPT`), sanction escalation 1->2->3 with suspend-then-full-family-sanction closure plus assignment termination, authorization voiding, recoupment pause, the supportive cap waterfall and fiscal-year derivation, the signed recovery ledger (satisfied -> reversal -> back to IN_RECOVERY), fraud re-sizing at 25%, diversion accept + ineligibility window, and the federal WPR/CRC calculate-and-certify path.

Every remaining smoke "FAIL" was traced to a wrong expectation in my throwaway script, not to the implementation — each was re-checked against the PRD text: post-sanction grant is 37612 (`50150 x 0.25 = 12537.5 -> 12538` half-up on the *cut*, per §3.2 step five), good cause sets `compliance_status` to `EXEMPT` (not `ASSIGNED`), `ERR_CONCILIATION_NOT_COMPLETE` / `ERR_GOOD_CAUSE_ACTIVE` / `ERR_DIVERSION_INELIGIBILITY_ACTIVE` are 422 (not 409), the report field is `verification_source` (not `documentation_type`), `requested_program` is `DIVERSION_CONSIDERED`, `youngest_child_age_months` is a required non-nullable integer, and a per-month `compliance_flag` update touches only the assignment being verified (§3.6) — corroborated by the same run reporting `wpr_all_families_pct == 100.00`.

## Step 7: Run tests and iterate — 2026-09-02T20:23:00.000Z

ORCHESTRATOR INDEPENDENT VERIFICATION (per standing caution that a Step 7 subagent can claim a clean sweep while leaving no artifacts): re-checked the artifacts myself rather than trusting the subagent's report. All 8 `workspace/implementation/results.{1..8}.json` exist, ~30.6 KB each, timestamped 20:15, and each parses to `passed=101 total=101 failed=0 errors=0 skipped=0`. Grepped `test_suite/` + `test_helpers/` for `mark.skip` / `mark.xfail` — zero hits, so the green result is not masking suppressed tests. Zero `__pycache__` directories remain under the task dir. Sweep was run under `setsid nohup` and showed no reaping signature.

Verbatim subagent summary follows.

Clean sweep on the first iteration — no test or implementation changes were needed.

**Iterations run:** 1 (single 8-round parallel sweep, all rounds launched concurrently under `setsid nohup`, joined with `wait`, no early exit).

**Tests deleted:** none. No test failed in any of the 8 rounds, so no test entered the diagnostic protocol (STEP 0 produced an empty union set).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Final results (literal `passed/total` from each file in `workspace/implementation/`):**

| File | passed/total | failed | errors | skipped |
|---|---|---|---|---|
| results.1.json | 101/101 | 0 | 0 | 0 |
| results.2.json | 101/101 | 0 | 0 | 0 |
| results.3.json | 101/101 | 0 | 0 | 0 |
| results.4.json | 101/101 | 0 | 0 | 0 |
| results.5.json | 101/101 | 0 | 0 | 0 |
| results.6.json | 101/101 | 0 | 0 | 0 |
| results.7.json | 101/101 | 0 | 0 | 0 |
| results.8.json | 101/101 | 0 | 0 | 0 |

**Verification notes:**
- All 8 `results.{1..8}.json` exist, are non-empty (~30.6 KB each), and were written by this sweep (timestamps 20:15, all 8 concurrent rounds completed; total wall time ~7 min for the whole sweep).
- No round showed the `setsid`-reaping signature (no round-wide simultaneous death, no RemoteDisconnected/ConnectionResetError). The `Killed` lines in `workspace/sweep.log` are the runner's own `kill -9` of the per-test server under `--isolation per-test-server`, which is expected.
- Confirmed `0 skipped` in every round and grepped `test_suite/` + `test_helpers/` for `pytest.mark.skip` / `pytest.mark.xfail` — none present, so the green result is not masking suppressed tests.
- `__pycache__` removed from `test_suite/`, `test_helpers/`, `workspace/implementation/`, and `workspace/implementation/routes/` (0 remaining anywhere under the task dir).

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T20:24:00.000Z

SKIPPED per the skill's explicit skip condition. Step 7 exited on the FIRST 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — i.e. zero iterations beyond the baseline. With an empty `<step_7_diff>` there is no PRD-silence or PRD-mismatch site for Step 8 to target: `PRD.md` already determined every behavior the implementation exhibits at every point the 101-test suite exercised. Spawning the subagent would give it nothing in scope to patch and would risk unbounded edits, violating Step 8's HARD SCOPE rule. Consequently `workspace/PRD_FINALIZED.md` is intentionally absent, and Step 9 starts from `workspace/PRD.md` per its stated input fallback.

Decision made autonomously by the orchestrator (running non-interactively; no user available to confirm).

## Step 9: Complete PRD — 2026-09-02T20:29:00.000Z

ORCHESTRATOR VERIFICATION: `workspace/PRD_COMPLETED.md` exists (103,846 bytes), holds the same 29 section headings as `PRD.md` (no sections added or dropped), and ends on the final §5 row `| \`ERR_DIVERSION_REQUIRES_BENEFIT\` | 422 |` — a clean table close, not truncated. Started from `PRD.md` because Step 8 was skipped and `PRD_FINALIZED.md` is intentionally absent.

Verbatim subagent summary follows.

Done. `PRD_COMPLETED.md` is written and verified: 487 lines (same as source — every change is an in-paragraph edit), ends with the full §5 error-code table, no sections added.

## Counts
- **Source** `PRD.md`: 487 lines / 96,373 chars -> **`PRD_COMPLETED.md`**: 487 lines / 103,846 chars (**+7,473 chars**)
- 27 lines changed, all clean 1-for-1 replacements (29 logical edits; para 189 and para 245 each took two)
- **Ambiguity-pins: 25** · **Mismatch-revisions: 4**

## Changes
- §2.1 — insert — ambiguity — whitespace-only auth headers count as absent — `guards.py:37`
- §2.1 — insert — ambiguity — SoD check passes when the paired identifier is still null, so approving a `RECEIVED` app gives the state error — `guards.py:56`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` -> `ERR_INVALID_REQUEST`; empty string = absent — `respond.py:59-69`
- §2.3 — insert — ambiguity — filter query params are never schema-validated; an unknown value matches nothing — `respond.py:83-87`
- §2.4 — **revise** — **mismatch** — a no-op recompute is not a mutation, and a row's `version` advances by exactly one per request no matter how many cascade steps touch it — `store.py:142,157`
- §3.1 — insert — ambiguity — `head_of_household_name` may not be blank — `households.py:26`
- §3.1 — insert — ambiguity — `source_state_code` non-blank, both carried-in counts >= 0 — `households.py:84-86`
- §3.2 — insert — ambiguity — `month_1/2/3_cents` have no lower bound — `applications.py:88-90`
- §3.2 — insert — ambiguity — verification body field is `verification_status`; not gated on application status or prior source status — `applications.py:130`
- §3.2 — insert — ambiguity — `encumbrance_cents` has no lower bound — `applications.py:143`
- §3.2 — insert — ambiguity — determination reads the household's live `household_size`; leaves `decided_by_user_id` null — `applications.py:189`
- §3.3 — insert — ambiguity — `case_number` is `CASE-` + 6-digit counter from `000001` per process — `store.py:50`
- §3.3 — **revise** — **mismatch** — denial *does* record `decided_by_user_id` (PRD said "nothing else changes") — `applications.py:274`
- §3.3 — insert — ambiguity — the diversion offer takes no request body and leaves `decided_by_user_id` null — `applications.py:300`
- §3.4 — insert — ambiguity — time-limit closure also voids the terminated assignments' authorizations and recomputes `supportive_fy_authorized_cents`; the issuance response is the ledger row — `domain.py:225-233`, `cases.py:86`
- §3.4 — insert — ambiguity — extension denial records `decided_by_user_id` — `cases.py:185`
- §3.4 — insert — ambiguity — revocation overwrites `decided_by_user_id` — `cases.py:204`
- §3.4 — insert — ambiguity — revocation-driven closure is narrow: no assignment termination, no void, no recoupment pause, no sibling-extension re-check — `cases.py:209-213`
- §3.5 — insert — ambiguity — no `start_date`/`end_date` ordering rule and no case-posture gate at assignment creation — `work.py:39-51`
- §3.6 — insert — ambiguity — filing a report is not gated on the assignment's own status — `work.py:139`
- §3.6 — **revise** — **mismatch** — the `verified_hours` band check is ladder-5 and runs *before* both state checks (PRD listed it last) — `work.py:194-202`
- §3.6 — insert — ambiguity — a system-opened episode carries `prior_episode_id` null — `work.py:225`
- §3.7 — insert — ambiguity — good cause does not unsuspend the case or resume paused recoupment, and `ERR_GOOD_CAUSE_ACTIVE` outranks the episode-state error — `compliance.py:134-152,183`
- §3.7 — insert — ambiguity — full-family-sanction closure voids the terminated assignments' authorizations; suspend/close and the recoupment pause fire only on an actual transition — `compliance.py:30-46`
- §3.8 — **revise** — **mismatch** — `period_end` before `period_start` is refused with `ERR_SERVICE_PERIOD_OVERLAP`, not `ERR_INVALID_REQUEST`, and is checked before the overlap scan — `supportive.py:51-53`
- §3.8 — insert — ambiguity — the void-time rollup also uses the clock's *current* fiscal year, not the voided row's — `supportive.py:139`
- §3.9 — insert — ambiguity — `offsetting_underpayment_cents` has no lower bound — `overpayments.py:40`
- §3.9 — insert — ambiguity — fraud disposition is gated only on `fraud_referral_status == REFERRED`; claim status is not consulted — `overpayments.py:209-211`
- §3.10 — insert — ambiguity — both caseload inputs accept decimals; `fiscal_year` is an unbounded integer — `reporting.py:87-90`

**No change needed** for §4 (all 66 role assignments and every 201-vs-200 code match the blueprints) or §5 (all 51 identifiers and HTTP statuses match `errors.py` exactly). Two apparent §2.8 ladder tensions — good-cause-before-episode-state and the verify band check — were already resolvable from PRD prose plus the ladder, and I pinned both inline rather than touching §2.8 itself.

---

## PIPELINE COMPLETE — 2026-09-02T20:29:00.000Z

All 9 steps done (Step 8 skipped by its stated skip condition). Final deliverable state:
- `SCAFFOLD.yaml` (150 KB), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (171 KB), `SCAFFOLD_CORNER_DESIGN.yaml` (131 KB) — clean lint
- `test_helpers/` (9 modules), `test_suite/` (conftest + 17 files, 101 tests)
- `workspace/PRD.md` (487 lines), `workspace/PRD_COMPLETED.md` (487 lines), `workspace/INSTRUCTION.md`
- `workspace/implementation/` — Python + Flask, 65/65 endpoints, in-memory only, no seeded data
- `workspace/implementation/results.{1..8}.json` — 101/101 in all 8 rounds
