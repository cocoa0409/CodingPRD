# Worklog — task_2475_customer_success_renewal_health_scoring

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2475_customer_success_renewal_health_scoring/` and its `workspace/` subdirectory. Index 2475 was pre-assigned by the invoker; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T00:35:00.000Z

All three artifacts are complete and lint-clean. Final linter run (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2475_customer_success_renewal_health_scoring/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2475_customer_success_renewal_health_scoring/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2475_customer_success_renewal_health_scoring/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     14
  §1.8 instances scanned:     27
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  535

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Generated files

- SCAFFOLD.yaml
- SCAFFOLD_DIFFICULTY_DESIGN.yaml
- SCAFFOLD_CORNER_DESIGN.yaml

## Counts

SCAFFOLD.yaml (§1.0–§1.7), `api_prefix: ""`, expert-plus band:
- 14 entities, 11 state machines, 2 concurrency rules (OCC on Account and EscalationCase)
- 23 calculations, 32 ordered validations, 56 endpoints (E1–E56), 43 error codes, 6 roles

SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8): 9 rule_ids × 3 instances = 27 instances, 277 calls.

SCAFFOLD_CORNER_DESIGN.yaml (§1.9): all 9 taxonomy sections, 62 instances = 54 real + 8 `excluded_because:` stubs — entities 12, state_machines 12 (3 stubs), calculations 8 (2 stubs), validations 10 (1 stub), endpoints 5, errors 5, rbac 4, cross_cutting_complexity_layers 5 (2 stubs), consistency_model 1. Every stub's cited difficulty instance resolves by name in §1.8; no stub carries a `test_recipe`. All 81 instance names are unique across the union of both design files.

## Adjudications

- Merged the usage-snapshot and support-ticket tables into one polymorphic `AccountSignal` entity (`common_fields: false`) rather than two near-duplicate entities; no separate WinBackCampaign entity (win-back is a lifecycle action on Account with `churn_root_cause_code` gating).
- Account create runs an immediate deterministic health recompute, so a fresh ENTERPRISE account is 43.75 / RED, `coverage_tier UNASSIGNED`, `coverage_posture RESTRICTED`, `renewal_likelihood AT_RISK`, version 1.
- Health score is dual-variant: snapshot (newest usage row only) vs trended (3-row window), with `health_tier` derived from the snapshot variant only and `qualification_score` from the trended variant — the divergence is a §1.8 depth target.
- `ttv_breach_flag` is raised by the daily sweep and drives coverage posture FROZEN plus BLOCKED milestones, unwound only by `WAIVE_TTV_BREACH`.
- Over-capacity coverage assignment stays QUEUED (not an error); a capacity *reduction* below committed is `ERR_CSM_CAPACITY_EXHAUSTED` (409).
- Validation-18 tier gates kept asymmetric on purpose: `{RED, AMBER}` to activate a SavePlay, `{AMBER, GREEN}` to hand off an opportunity or ACTIVATE an advocacy enrollment, `{GREEN}` only to APPROVE an enrollment. This forced an ACTIVE CXO economic-buyer sponsor plus an explicit health-recompute in the GREEN-path corner recipes (sponsor-contact create is not itself a recompute trigger — only PATCH is).
- Segregation of duties is keyed on `X-User-ID`, not role: the executive who ACCEPTed a remediation commitment cannot DELIVER it. Credit ledger semantics: ACCEPTED/DELIVERED on a live case count as outstanding; settlement only occurs on case RESOLVED.

Every numeric literal in both design files was executed against the §1.3 formulas (Decimal, ROUND_HALF_UP) before being written — e.g. load_units 19/17/16 for a RED/AMBER/GREEN ENTERPRISE 30M account, the strict-`>` 5% variance tolerance, the 60-day support window boundary, and the SMB reference-call cap of 2.

## Step 3: Copy shared files — 2026-09-03T00:36:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T00:55:00.000Z

PRD generation is complete and verified.

**Deliverable:** `workspace/PRD.md` — 459 lines, ~115 KB.

**Structure:** 5 top-level sections, 19 subsections — §1 Introduction; §2 Global Specifications (10 subsections: RBAC, Response Structure, Pagination, Resource Identity/Mutation Counters/Immutable Signal Rows, Logical Clock & Interval Conventions, Decimal Discipline, Stale-Read Protection, Coverage Posture, The Validation Ladder, Conserved Counters & Cascade Discipline); §3 Business Logic (9 subsections, 164 lines: intake/onboarding/TTV, signals & dual health score, executive & outcome commitments, segmentation/capacity/coverage, save plays & escalation negotiation, forecasting & reconciliation, expansion & handoff, advocacy, lifecycle endgame & sweep); §4 Endpoint Definitions; §5 Error Code Catalogue.

**Anti-truncation verification (scripted, not eyeballed):**
- File ends at a real boundary — the last complete row of the §5 table (`ERR_REFERENCE_CALL_CAP_REACHED | 409`). No sentinel marker remains, no mid-sentence or mid-table cut.
- **Endpoints: 56/56.** Every scaffold endpoint E1–E56 matched by exact method + exact path in the §4 table (56 table rows, zero missing, zero extras), and all 56 role lists match the scaffold set-for-set.
- **Error codes: 43/43** in §5 with exact HTTP statuses (zero missing, zero mismatched, zero extras). All 43 are also referenced in the §2/§3 prose next to the rule they guard.

Orchestrator independently re-verified the tail: file ends mid-table-free at a complete `| \`ERR_REFERENCE_CALL_CAP_REACHED\` | 409 |` row, 43 distinct ERR_ tokens present, 27 markdown headings. Not truncated.

**Hard Contract reports:**
- **Contract 1 — Field-Name Coverage: PASS.** 121/121 required identifiers appear verbatim in backticks (all 14 entities' fields, all request-body/path/query identifiers including `expected_account_version`, `expected_escalation_case_version`, `new_contract_end_date`, `current_utc`, and all projection outputs `support_component`, `variant_delta`, `usage_rows_considered`, `milestones_marked_overdue`, `commitments_breached`, `opportunities_expired`, `accounts_repostured`). The only unticked scaffold names are the six internal *calculation variant* labels (`snapshot_health`, `trended_health`, `contractual_ttv`, `activation_ttv`, `cs_bottom_up`, `finance_top_down`), which are not fields and are rendered in prose.
- **Contract 2 — Rule Coverage: PASS.** All 11 state machines (every transition with preconditions, error IDs and side effects, including the 4-link coverage release cascade and the 4-link breach cascade), all 23 calculations with every constant embedded in business context and the pinned rounding/ordering warnings preserved, all 32 validations in priority order with statuses and `applies_to` scopes (§2.9), both OCC rules (§2.7), both conserved-counter invariants (§2.10, §3.4, §3.5), and sibling-branch symmetry (e.g. the four asymmetric CHURN cascades, snapshot-vs-trended, contractual-vs-activation TTV, cs-vs-finance forecast).
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 begin with `/`, zero are bare HTTP methods, zero combine method+path; zero raw path-like strings appear either. Endpoints are referenced only by state-transition framing, role+verb, or capability description. Paths appear only in §2 and §4.

Also confirmed: §2.2 is byte-identical to `section-2.2-response-structure.md`; no banned OCC framing ("simultaneously", "first-writer-wins", "race", "winner/loser") appears anywhere.

**Zero-Silence decisions** (scaffold gaps or internal conflicts resolved without opening either withheld design file):
1. `OPPORTUNITY_STALE_DAYS` is referenced four times but never assigned a value → fixed at **30 days**, stated explicitly (strict `>`) in §3.7 and §3.9.
2. `outcome_attainment_index` input set: the calculation includes `DEFINED` goals, the field description says only `IN_PROGRESS`/`ATTAINED`/`MISSED` → followed the **calculation** (DEFINED included), which is what makes the "60.00 substitute stops applying once the first goal exists" side effect coherent.
3. Coverage-assignment create ordering: the admission test runs **before** supersession (per the endpoint's side-effect order), and to resolve the resulting conflict with the `COMMITTED → PREEMPTED` "clear `assigned_csm_id`" side effect, `assigned_csm_id` is stated as an invariant — it names the CSM of the account's single `COMMITTED` assignment and is null only when none remains.
4. Sweep semantics: fixed pass order (overdue milestones → commitment breaches → opportunity expiry → TTV flag + posture re-derivation last), and `accounts_repostured` defined as the count of accounts whose `coverage_posture` value differs after the sweep.
5. Forecast submit is gated on posture not `FROZEN` (the endpoint's error list declares `ERR_COVERAGE_POSTURE_FROZEN` even though validation 13's `applies_to` omits submit); documented in §3.6 while §2.9 keeps the ladder's literal scope.
6. Header naming: used the skill's fixed `X-User-ID` / `X-User-Role` contract rather than the scaffold's shorthand "X-Role".

## Step 5: Generate unit tests — 2026-09-03T01:40:00.000Z

The suite is complete and audited clean.

## Files written

**Stage 1 — `test_helpers/`** (9 modules): `constants.py`, `types.py`, `api_errors.py`, `api_client.py`, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py`, `__init__.py`. Plus `test_suite/conftest.py` registering all 16 function-scoped fixtures (no session scope — the harness restarts the server before every test).

**Stage 2 — `test_suite/`** (18 files, **132 test functions / 135 collected cases**):

| file | tests | file | tests |
|---|---|---|---|
| test_01_dual_variant_calculations | 9 | test_10_entity_contracts | 12 |
| test_02_combinatorial_formulas | 11 | test_11_state_machine_corners | 9 |
| test_03_boundary_precision | 8 | test_12_calculation_corners | 6 |
| test_04_non_linear_state_machines | 10 | test_13_validation_corners | 10 |
| test_05_transitive_cascades | 9 | test_14_endpoint_corners | 5 |
| test_06_validation_priority_conflicts | 8 | test_15_error_corners | 6 |
| test_07_cross_entity_state_dependency | 8 | test_16_rbac | 7 |
| test_08_resource_temporal_overlap | 4 | test_17_cross_cutting_layers | 5 |
| test_09_compensating_invariants | 4 | test_18_consistency_model | 1 |

## Coverage

- **Queue A (depth):** 27/27 instances translated, all at >= 2 tests. Nothing skipped.
- **Queue B (breadth):** 54/54 non-stub instances translated, all at >= 1 test. Nothing skipped.
- **8 verified-then-untranslated stubs:** all confirmed to hold 0 tests, and each one's `difficulty_instance:` cross-reference was checked to resolve to a real queue-A name.

## Audit results (all green)

Every `def test_` carries exactly one `Design:` line, verbatim from the source yaml, as the last non-blank docstring line; every tag resolves to a live instance. All ~410 `PRD §N.N: "..."` citations are byte-exact substrings of `workspace/PRD.md`. Zero `skip`/`xfail`, zero banned vocabulary. `compileall`, `pyflakes` and `pytest --collect-only` are clean; `import test_helpers` exposes 421 symbols with the error/status map registered.

## Two things worth flagging

1. **One instance is only partially translatable and only the derivable half was translated.** `cross_entity_state_dependency/forecast_submit_depends_on_a_committed_coverage_assignment` asks for `ERR_INVALID_STATE_TRANSITION` on an unstaffed submit, but the PRD does not derive that id: §2.9 rule 12 fires only on undeclared edges and `DRAFT → SUBMITTED` is declared, while rule 13 needs a `FROZEN` posture (the scenario's is `RESTRICTED`). The refusal test therefore asserts that the submit does not succeed and the row stays `DRAFT` with `submitted_at` null, without pinning an id; the companion test asserts the full positive outcome (`SUBMITTED`, `submitted_at` stamped, `cs_amount_cents` 21,000,000, `finance_state` still `PENDING`, assignment `COMMITTED` at 17 units). This is the one place in the suite where a design-index assertion was narrowed rather than reproduced.

2. **Several design-index literals were unreachable and were re-grounded on the PRD**, all reported by the workers and re-checked: the §3.5 "no delivered commitment settles at 450,000" contrast (RESOLVE requires a `DELIVERED` commitment, so the same 405,000 is reached via a `MEDIUM` case), the §3.4 `LOW_TOUCH` "8.25 plus 2" example (a 30,000,000 account always segments `HIGH_TOUCH`, so ARR 10,000,000 with surcharge 1 is used), the `MERGER_ACQUISITION` churn asserting `AT_RISK` rather than `OMIT` (§3.9: churning from `ONBOARDING` does not recompute likelihood), and the segregation-of-duties / stale-version corners rebuilt on a `COMMITTED` case. Exact clock-derived timestamp strings are asserted non-null rather than literal, since §2.4 fixes three fractional digits while the yaml wrote `Z`-suffixed whole seconds.

## Step 6: Generate implementation — 2026-09-03T01:40:00.000Z

The implementation is complete and verified.

## Files written — 33 files under `workspace/implementation/`

- Root: `app.py`, `db.py`, `dt_util.py`, `errors.py`, `middleware.py`, `response.py`, `requirements.txt`, `start.sh` (executable)
- `routes/` (`__init__.py` + 14 blueprint modules): `accounts`, `csms`, `coverage_assignments`, `signals`, `sponsors`, `engagements`, `goals`, `milestones`, `save_plays`, `escalations`, `forecasts`, `expansion`, `advocacy`, `ops`
- `services/` (`__init__.py` + 10 modules): `calc`, `derive`, `serialize`, `lookup`, `coverage`, `risk`, `sweep`, `lifecycle`, `gates`

## Endpoints — 56 of 56 (E1–E56)

accounts 8, csms 3, coverage-assignments 4, signals 2, sponsor-contacts 4, executive-engagements 4, outcome-goals 3, onboarding-milestones 3, save-plays 4, escalations (cases + remediation commitments) 7, renewal-forecasts 5, expansion-opportunities 4, advocacy-enrollments 3, ops (`/_clock/set_current_utc`, `/_ops/daily-sweep`) 2.

## `start.sh` / boot contract

`start.sh` cds to its own directory, pip-installs Flask only if the import fails (deliberately conditional so eight concurrent per-test reboots don't contend), then `exec python3 app.py` — so the server runs in the **foreground** as PID of the script. `app.py`'s `__main__` block binds `host='0.0.0.0'` on `int(os.environ.get('PORT', '10000'))`, single-process, `threaded=True`, `use_reloader=False`. Verified booting on both `PORT=18475` and the default 10000, answering on `http://0.0.0.0:10000/accounts`.

## Storage / seeding

In-memory Python dicts keyed by UUID in `db.py` only — no SQLite, no JSON dump, no `/tmp` cache, no `atexit` persistence. A cold boot returns `total_count: 0` for every collection (confirmed on `/accounts` and `/expansion-opportunities`), so per-test-server isolation starts from genuinely empty state every time.

## Notable fidelity decisions

- Every window/aging/sweep computation reads the logical clock (default `2026-08-01T00:00:00Z`); wall clock is used only for `created_at`/`updated_at`/`api_request_timestamp`.
- All money/score math uses `Decimal` with ROUND_HALF_UP (one ROUND_CEILING for coverage load units); basis-point comparisons use integer cross-multiplication.
- Request-scoped change tracking guarantees exactly one `version` bump plus one `updated_at` refresh per mutated row per request, and never bumps a row created in the same request.
- The 32-rule validation ladder is enforced first-violation-wins, including the two documented inversions: rule 8 (segregation of duties) and rule 7 (handoff ownership) are both checked before rule 12 (edge existence).
- Where SCAFFOLD.yaml conflicted with the PRD, the PRD won: SCAFFOLD's claimed per-account uniqueness of AdvocacyEnrollment `program_type` is not implemented, since the PRD states no such rule and no error id exists for it.
- Numeric behaviour was smoke-checked against the PRD's worked examples (43.75/RED/AT_RISK/RESTRICTED first pass, 10,500,000 vs 27,000,000 with a 16,500,000 flagged variance, 800,000 settlement credit, qualification scores 39.38/92.38, load units 19/14, the 30-minute engagement buffer boundary), plus the four sweep counters, the four-link breach cascade, and RENEW/CHURN/WIN_BACK_TARGET/REACTIVATE.

No server processes remain running; port 10000 is free for the harness, and `__pycache__` directories were removed.

## Step 7: Run tests and iterate — 2026-09-03T02:05:00.000Z

**Iterations run:** 2 (two full 8-round parallel sweeps).

**Iteration 1 result:** 122/135 in all 8 rounds — a stable, non-flaky union of 13 failing tests.

**Tests deleted:** none. No asserted rule turned out to be PRD-silent at the whole-test level.

**Assertions removed under STEP 1c (partial coverage):**
- `test_suite/test_10_entity_contracts.py` → `TestAccountCreationContract::test_create_stamps_a_server_id_the_logical_clock_and_version_one`: dropped the two assertions that `created_at` / `updated_at` must start with `2026-08-01T00:00:00` (the logical clock). PRD §2.4 fixes only their *shape* ("an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written") and never names the clock they read; §2.5's absolute clause enumerates "every window, every sweep, every date difference and every 'is this in the past' test", none of which is a creation stamp. **DEFAULT-VALUE / COMPUTED-FIELD SILENCE**: both readings are PRD-faithful, and the wall-clock reading is arguably required, since §2.3 and §3.2/§3.4 use `created_at` ascending as a *tie-break* — which a frozen logical clock would collapse. The `id`-is-a-UUID, `version == 1`, and re-read-consistency assertions (all verbatim in §2.4) were kept. Comparable assertions on `identified_at` and `outcome_recorded_at` were left untouched, because PRD does say those are "stamped from the logical clock".

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_client.py` — added `ApiClient.patch()`. `GenericApiClient` from the runner ships only get/post/put/delete, so all three PRD §4 PATCH endpoints (`PATCH /accounts/{id}`, `/csms/{id}`, `/sponsor-contacts/{id}`) raised `AttributeError` before any request left the client. This single upstream helper bug accounted for 8 of the 13 failures.

**Fixes applied to `test_suite/`** (assertion/call-site mis-translations, not weakenings):
- `test_13_validation_corners.py` — `TestMilestoneSequence::test_completing_out_of_sequence_is_refused` called `read_milestone(api, id)` with the `account_id` argument missing (`TypeError`). Passed the account id through.
- `test_14_endpoint_corners.py` — `TestHealthRecompute::test_recompute_drops_a_ticket_that_aged_out_of_the_support_window` had a corrupted `add_support_signal(...)` call with three stray positional args (`SEVERITY_MEDIUM`, `SEVERITY_S1`, `SOURCE_EXEC_REQUEST`). Reduced to `SEVERITY_S1`, which is the severity the test's own `penalty_points == 12` assertion and its cited §3.2 sentence require.

**Fixes applied to `implementation/`:**
- `workspace/implementation/services/lifecycle.py`, `apply_action()` — added `derive.recompute_renewal_likelihood(account)` to the `RENEW`, `WIN_BACK_TARGET`, `ARCHIVE` and `WAIVE_TTV_BREACH` branches. PRD §3.2 states verbatim "The category is recomputed on every health recompute, on every account lifecycle transition, and on every save-play transition into a terminal state"; §3.9 carves out exactly one exception ("Churning from `ONBOARDING` … does not recompute `renewal_likelihood`"), which is preserved. Without this, an `ARCHIVED` account kept a stale `AT_RISK` instead of the `OMIT` §3.2 requires for `CHURNED`/`WIN_BACK_TARGETED`/`ARCHIVED`.

No implementation check was removed or weakened; no skip/xfail added; no seeded data; storage remains in-memory dicts.

**Final sweep (all 8 parallel rounds), quoted from `workspace/implementation/results.$i.json`:**

| round | passed / total |
|---|---|
| 1 | 135 / 135 |
| 2 | 135 / 135 |
| 3 | 135 / 135 |
| 4 | 135 / 135 |
| 5 | 135 / 135 |
| 6 | 135 / 135 |
| 7 | 135 / 135 |
| 8 | 135 / 135 |

Union of failures across all 8 rounds: **0**. All eight results files exist on disk with `passed == total == 135`.

**Orchestrator independent verification:** re-read all 8 results files directly — 8 files present on disk (each ~43.8 KB, mtime 2026-09-03 02:03), each reporting `passed=135 total=135 failed=0`. The Step 7 claim is corroborated, not taken on trust.

## Step 8: Finalize PRD — 2026-09-03T02:15:00.000Z

Done. `PRD_FINALIZED.md` created with three edits.

## Line counts
- `PRD.md`: 459 lines / 115,057 bytes
- `PRD_FINALIZED.md`: 459 lines / 116,595 bytes
- **Δ lines: 0 (0.0%)**; Δ bytes: +1,538 (+1.34%) — all three edits are in-place sentence revisions, no new sections or lines.

## Changes

- **§2.4 (Resource Identity)** — *insert* — pinned that `created_at` / `updated_at` are stamped from the server's **real wall clock**, explicitly *not* the §2.5 logical clock, and that any `created_at`-ascending order or tie-break falls back to insertion order when two rows share a `created_at` (never to the row `id`) — `implementation/db.py:71-83` (`wall_stamp`/`base_row`), `db.py:133-144` (`commit`), `db.py:152-153` (`ordered` → `(created_at, _seq)`).
- **§2.5 (Logical Clock)** — *revise* — replaced the false universal "Nothing in this system reads the wall clock" with "No business rule … reads the wall clock", naming the two exceptions (`api_request_timestamp`, `created_at`/`updated_at`) and listing the seven server-stamped instants that *do* read the logical clock — `implementation/response.py:21`, `db.py:78/138`, `db.py:53` (`clock_stamp`).
- **§3.2 (renewal_likelihood)** — *revise* — replaced the blanket "on every account lifecycle transition" with the six client-driven lifecycle actions enumerated, stated the blanket overrides the per-action prose of §3.1/§3.9, and carved out the `ONBOARDING → ADOPTING` system move — `implementation/services/lifecycle.py:82,112,129,147,161,172` (recompute present) vs `lifecycle.py:179-194` (`evaluate_onboarding_completion`, no recompute).

**No PRD edit** for the three fixture-level items (`test_helpers/api_client.py` missing `ApiClient.patch()`, `test_13` missing `account_id` arg, `test_14` stray positional args): all three PATCH routes exist at `routes/accounts.py:107`, `routes/csms.py:45`, `routes/sponsors.py:63` and are already published in §4 — the failures were client/test-call bugs, not PRD silence.

## Per-edit pre-edit search log

**Edit 1 (§2.4)**
- (a) Subject: which clock stamps `created_at`/`updated_at`, and how equal `created_at` values are broken.
- (b) Enumerated/read: `db.py:63-64` (`utc_now`), `db.py:71-83` (`wall_stamp`, `base_row`), `db.py:107-144` (`mark_fresh`/`track`/`touch`/`commit`), `db.py:44-58` (logical-clock accessors), `db.py:152-224` (`ordered` + all 14 per-parent accessors), `services/derive.py:15-21` (usage-row ordering), `services/coverage.py:29-44` (`eligible_pool`/`select_csm` ranking), `services/coverage.py:84-93` (`promote_queued` lowest-`created_at`), `services/sweep.py:14,22,35,44`, list handlers in `routes/accounts.py:93`, `routes/coverage_assignments.py:98`, `routes/escalations.py:79`, `routes/expansion.py:85`, `routes/save_plays.py:89`, `response.py:14-25`, `services/serialize.py:22-28,93-112` (signal rows carry no `updated_at`/`version`).
- (c) Adjustment: scoped the wall-clock claim to `created_at`/`updated_at` as *row* fields only (so §2.2's `api_request_timestamp` is not contradicted, and no claim is made about the logical-clock stamps); phrased the fallback as "the order in which those rows were inserted" and added "the row's `id` is never used to break a tie" so §3.4's "the manager's identifier is never used to break a tie" and §3.2's "`created_at` ascending as the only tie-break" both remain true.

**Edit 2 (§2.5)**
- (a) Subject: the universal "nothing reads the wall clock" claim, and the clock behind every server-stamped instant.
- (b) Enumerated/grepped: `grep -rn "utc_now|wall_stamp|datetime.utcnow|db.now()|clock_stamp|db.today()"` — wall clock only at `db.py:78`, `db.py:138`, `response.py:21`; logical clock at `services/coverage.py:57,75,97,111`, `services/lifecycle.py:41,99,136,142-143`, `routes/engagements.py:120,123,130`, `routes/expansion.py:43-44`, `routes/advocacy.py:117`, `routes/forecasts.py:142,181`, `routes/accounts.py:116`, `services/derive.py:25,55,139,195`, `services/sweep.py:13`. Cross-checked `grep -rn "_at'"` against `services/serialize.py` to confirm the seven server-stamped instants are exhaustive and that `start_at`/`end_at`/`opened_at`/`resolved_at` are client-supplied (neither clock).
- (c) Adjustment: named the two exceptions instead of deleting the guarantee; kept the "every window / sweep / date difference / is-this-in-the-past" clause verbatim; listed exactly the seven server-stamped logical-clock instants (verified exhaustive) rather than saying "all other timestamps", which would have wrongly captured the client-supplied instants.

**Edit 3 (§3.2)**
- (a) Subject: which transitions recompute `renewal_likelihood`.
- (b) Enumerated (all 19 `recompute_renewal_likelihood` callsites read): `services/lifecycle.py:82` (RENEW), `:112` (CHURN, guarded `if state != 'ONBOARDING'`), `:129` (WIN_BACK_TARGET), `:147` (REACTIVATE), `:161` (ARCHIVE), `:172` (WAIVE_TTV_BREACH), `:217` (four health-driven edges); `lifecycle.py:179-194` `evaluate_onboarding_completion` — **no** recompute; `services/risk.py:30` (`fail_save_play`, also the sweep breach path); `routes/save_plays.py:145` (SUCCEED), `:172` (ABANDON, from `DRAFT` and from `ACTIVE`); `routes/accounts.py:72,138,142,181`; `routes/signals.py:94`; `routes/goals.py:26` (creation only — `_recompute_after_progress` omits it); `routes/sponsors.py:84` (patch only — `create_sponsor` at `:38-40` omits it); `routes/engagements.py:135` (HELD/NO_SHOW only).
- (c) Adjustment: dropped the blanket "every account lifecycle transition" in favour of the explicit six-action list, because the blanket is false for `ONBOARDING → ADOPTING` (`lifecycle.py:179-194`) — strengthening the blanket would have created a new mismatch. Kept "every save-play transition into a terminal state" verbatim (verified true for SUCCEED, FAIL and ABANDON, including ABANDON from `DRAFT`). Kept the sentence non-exhaustive so the other triggers stated elsewhere in the PRD (account create/patch, signal submission, goal creation, sponsor patch, engagement outcome) remain valid, and added an explicit pointer that the four health-driven edges do recompute (already pinned earlier in §3.2).

## Step 9: Complete PRD — 2026-09-03T02:40:00.000Z

PRD_COMPLETED.md is finished at `workspace/PRD_COMPLETED.md`.

**Size**
- `PRD_FINALIZED.md`: 459 lines, 116,595 chars
- `PRD_COMPLETED.md`: 459 lines, 128,712 chars (+12,117 chars)
- 26 paragraphs touched, all in-place prose edits — no new sections, no new paragraphs, no table or heading altered. File ends at a real boundary: the last row of the §5 error catalogue, `| ERR_REFERENCE_CALL_CAP_REACHED | 409 |`.

**Counts**: 31 changes — 26 ambiguity-pins, 5 mismatch-revisions.

**Changes**
- §2.3 Pagination — insert — ambiguity — `limit`/`offset` must be plainly spelled integers; an empty-string parameter takes its default — middleware.py:212-238
- §2.3 Pagination — insert — ambiguity — empty filter value applies no filter; non-empty value outside a filter enum is 400; unmatched id filter yields an empty page, not 404 — middleware.py:241-254
- §2.4 Identity/version — insert — ambiguity — collateral version bumps are value-sensitive (no-op recompute leaves `version`/`updated_at`), while the row named in the path always advances — db.py:92-144
- §2.5 Logical clock — insert — ambiguity — accepted instant forms (optional seconds/fraction, `Z` or offset); client-supplied dates/instants echoed verbatim, only server-minted stamps canonicalised, including the clock echo — dt_util.py:9-56, routes/ops.py:12-19
- §2.6 Decimal discipline — insert — ambiguity — `feature_depth_pct`, `target_value`, `actual_value` are client inputs rendered in natural JSON-number shape, unpadded — services/serialize.py:5-19
- §2.7 Stale-read protection — insert — ambiguity — account `version` moves only when an account field actually changed, so a create that stays `QUEUED` leaves the same `expected_account_version` valid — db.py:92-144, routes/coverage_assignments.py:60-78
- §2.9 rule 5 — insert — ambiguity — strings non-empty after trim; only `name`, `full_name` (120) and `release_reason` (240) capped; non-negative `_cents`/counters; `estimated_value_cents` >= 1 — middleware.py:74-120, routes/expansion.py:61
- §2.9 rule 5 — insert — ambiguity — structural type checks (integer accepts `5.0`, rejects boolean/numeric string; enums/ids must be strings); explicit `null` counts as absent — middleware.py:100-156
- §2.9 rule 5 — insert — ambiguity — absent/whitespace body reads as `{}`; non-object JSON body violates the rule — middleware.py:47-58
- §3.1 Account amendment — insert — ambiguity — a patch naming none of the four fields is valid and still bumps `version`/`updated_at` — routes/accounts.py:107-144
- §3.1 Milestone completion — revise — **mismatch** — either `CsmUser` or `CsOpsAdmin` may complete or waive; the milestone's own state check precedes the posture and sequence gates — routes/milestones.py:76-99
- §3.1 Milestone waiver — insert — ambiguity — waiver has no posture gate; a `COMPLETED`/`WAIVED` target gives `ERR_INVALID_STATE_TRANSITION` — routes/milestones.py:106-111
- §3.2 Signals — insert — ambiguity — support-only fields on a usage row are silently ignored (rejection is one-directional); every row serialises the union with the other kind nulled; signals carry no `version` — routes/signals.py:63-66, services/serialize.py:88-118
- §3.2 Health projection — revise — **mismatch** — the projection also carries `account_id`, leading the field list — routes/accounts.py:205-217
- §3.3 Engagement outcome — insert — ambiguity — premature `HELD`/`NO_SHOW` give `ERR_INVALID_STATE_TRANSITION`; `CANCELLED` leaves `outcome_recorded_at` null — routes/engagements.py:120-130
- §3.3 Goal progress — revise — **mismatch** — lifecycle and shortfall refusals use `ERR_INVALID_STATE_TRANSITION`; omitted `actual_value` retained and read by the `ATTAINED` test; `health_tier` re-derived but not likelihood/posture — routes/goals.py:98-133
- §3.4 CSM patch — insert — ambiguity — a patch naming neither field is valid and still bumps `version` — routes/csms.py:46-64
- §3.4 Supersession — insert — ambiguity — units freed by a preemption promote nothing — services/coverage.py:63-82
- §3.4 Release promotion — insert — ambiguity — promotion does not re-test the manager's `status`, so an `ON_LEAVE`/`OFFBOARDED` manager still receives a promoted row — services/coverage.py:84-104
- §3.5 Save-play activation — insert — ambiguity — owner-must-be-`ACTIVE` gate gives `ERR_INVALID_STATE_TRANSITION` and sits between the tier gate (18) and the capacity gate (20) — routes/save_plays.py:114-124
- §3.5 Play closure — insert — ambiguity — the clear-of-escalations refusal on `SUCCEED`/`ABANDON` carries `ERR_INVALID_STATE_TRANSITION` — routes/save_plays.py:136-138, 161-163
- §3.5 Play closure — insert — ambiguity — omitted `outcome_note` leaves the stored value — routes/save_plays.py:141-142, 167-168
- §3.5 Escalation creation — insert — ambiguity — same-account membership is the only condition on the referenced play; its state and the posture are never examined — routes/escalations.py:43-47
- §3.5 Commitment transitions — insert — ambiguity — case-state and round-index preconditions give `ERR_INVALID_STATE_TRANSITION`, tested after the commitment's own state — routes/escalations.py:214-243
- §3.6 Forecast submit — insert — ambiguity — unstaffed/null-amount refusals give `ERR_INVALID_STATE_TRANSITION` and follow the frozen gate, while the two `cs_state` checks precede it — routes/forecasts.py:106-139
- §3.6 Revision edge — insert — ambiguity — leaves `submitted_at`, `reconciled_at` and `likelihood_category` untouched — routes/forecasts.py:116-128
- §3.6 Reconcile/lock — revise — **mismatch** — both actions require `cs_state` `SUBMITTED` (`ERR_FORECAST_NOT_SUBMITTED`); `RECONCILE` also requires `finance_state` `PENDING`; that and the `RECONCILED` precondition on `LOCK` give `ERR_INVALID_STATE_TRANSITION` — routes/forecasts.py:157-190
- §3.8 Enrollment creation — insert — ambiguity — no per-programme or per-account enrollment limit — routes/advocacy.py:24-45
- §3.8 Approval — revise — **mismatch** — any non-`OPEN` posture, `FROZEN` included, gives `ERR_COVERAGE_POSTURE_RESTRICTED`; posture precedes tier; no other action consults the posture — routes/advocacy.py:73-93, services/gates.py:12-17
- §3.8 Graduation — insert — ambiguity — the reference-call precondition gives `ERR_INVALID_STATE_TRANSITION`, not the cap code — routes/advocacy.py:120-128
- §3.9 Churn cascades — insert — ambiguity — cascade-released assignments get `released_at` but null `release_reason`; preempted `QUEUED` rows get `released_at` with null `superseded_by_assignment_id`; cascade-abandoned plays keep a null `outcome_note` and bypass the escalation-clear condition — services/lifecycle.py:91-110, services/coverage.py:107-113

**Deliberately left unpinned** (outside the PRD's declared surface, and pinning them would have meant new prose about undeclared behaviour): the `X-Role` fallback header accepted alongside `X-User-Role` (middleware.py:33-34); the 404/405/400/500 handlers that return `ERR_INVALID_REQUEST` with the raw HTTP status for undeclared routes and unexpected errors (app.py:51-72); and the `api_request_id` alphabet/length (`req_` + 24 lowercase alphanumerics, response.py:~20).

**Orchestrator independent verification:** `workspace/PRD_COMPLETED.md` is 459 lines / 128,712 chars, ends on a complete `| \`ERR_REFERENCE_CALL_CAP_REACHED\` | 409 |` table row (real section boundary, not truncated), and still contains all 43 distinct `ERR_` codes.

## Pipeline complete — 2026-09-03T02:42:00.000Z

All nine steps ran to completion. Final artifact set present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 modules), test_suite/ (18 files, 135 collected cases), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/, results.1-8.json}. Final stability sweep: 8/8 rounds at 135/135, zero failures, independently re-read from disk by the orchestrator.
