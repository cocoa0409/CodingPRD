# Worklog — task_2388_online_program_management_partnership_revenue

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2388_online_program_management_partnership_revenue/` and `tasks/task_2388_online_program_management_partnership_revenue/workspace/` (pre-allocated task name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-02T07:11:00.000Z

All three scaffold artifacts are complete and the linter is clean.

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_2388_online_program_management_partnership_revenue/`

**SCAFFOLD.yaml** (2,565 lines) — scenario 2388 verbatim, `api_prefix: "/"`, archetype `ledger_reconciliation` + `compliance_audit`, topology `graph`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`.
- **11 entities:** Partnership, Program, Course, ServiceScopeAssignment, EnrollmentCounselor, Lead, Enrollment, TuitionPayment, MarketingSpendEntry, RemittanceStatement, TeachOutPlan
- **8 state machines** (Partnership, Program, Course, EnrollmentCounselor *(parallel dimensions)*, Lead, Enrollment, RemittanceStatement *(fork-join + STALE cycle)*, TeachOutPlan)
- **2 OCC concurrency rules** on `Partnership.version` (statement create, terms patch)
- **10 calculations:** demand score (dual-variant SCREENING/CONFIRMED), recognized tuition revenue (dual-variant period vs milestone), partner share gross (tiered marginal), net remittance payable (waterfall), withdrawal refund + clawback, counselor conversion performance, teach-out obligation liability, blended CAC, plus two compensating-invariant reconciliations
- **49 ordered validations**, **49 errors** (all triggerable), **43 endpoints**, **6 roles**

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1,483 lines) — **9 rules × 2 instances = 18**, each pair differing on the rule's diversity axis (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade depth 4/3, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap half-open vs closed, compensating_invariant).

**SCAFFOLD_CORNER_DESIGN.yaml** (3,223 lines) — **9 sections, 84 instances = 73 full recipes + 11 `excluded_because` stubs**: entities 12, state_machines 12, calculations 10, validations 22, errors 10, endpoints 5, rbac 5, cross_cutting_complexity_layers 7, consistency_model 1.

**Verification**
- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (43 endpoints, 11 entities, 18 + 73 instances, 1,411 calls scanned)
- Uniqueness/structure audit: no duplicate names across both design files; every stub's `difficulty_instance` resolves; no stub carries a `test_recipe`; all 49 error codes referenced.
- Both mandatory replays run. Defects found and fixed during them: (a) `program_submit_below_the_screening_threshold` couldn't observe priority 42 because priority 36 (`ERR_NO_COURSES_DEFINED`) outranks it — added a course to the weak Program; (b) the refund-band instance aliased a withdrawal anchor pointed at the wrong Enrollment — replaced with an explicit call on the second enrollment; (c) `PATCH /courses/{id}` declared a nonexistent "Program design cost roll-up" side effect — reworded to the real teach-out liability inputs. Earlier session fixes retained: `PATCH /courses/{id}` added via §1.5 ladder rung 2 to make `ERR_PREREQUISITE_CYCLE` triggerable, four LAUNCH calls re-roled to `PartnerAccountLead`, and one invalid `generated_by` enum literal corrected.
- All money/score literals were computed with Decimal + ROUND_HALF_UP/ROUND_FLOOR scripts (e.g. Sept line 159198 → share 91539 → net 73919; Oct line 164505 → net 76382; per-line rounding sum 143751 ≠ 143750; refund bands 562500 vs 281250 at days 7/8; demand 44.90 / 62.00 / 61.90 / 69.00; teach-out 108000 = 0 + 43200 + 64800).

## Step 3: Copy shared files — 2026-09-02T07:13:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_2388_online_program_management_partnership_revenue/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T07:30:00.000Z

PRD generated and audited.

**Output:** `workspace/PRD.md` — 479 lines.

**Structure**
- `# Online Program Management Partnership API — Product Requirements Document`
- §1 Introduction (3 paragraphs: OPM partnership scenario, system scope, the two governing properties)
- §2 Global Specifications — 9 domain-derived subsections: 2.1 Actors/Headers/Partnership Scoping · 2.2 API Response Structure (byte-identical paste, verified) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Request Screening Order · 2.6 Optimistic Concurrency on the Partnership Record · 2.7 Money, Rounding and the Two Conserved Ledgers · 2.8 Derived Fields, Cascade Discipline and Hierarchical Consistency · 2.9 Segregation of Duties and Non-Delegable Responsibilities
- §3 Business Logic & Workflows — 9 freely-grouped subsections (contracting → program screening/review → academic content & service scope → launch/CIP exclusivity → counselor compensation compliance & performance → lead gen/marketing/conversion → tuition/withdrawal/refund/clawback → recognition/share/settlement → teach-out & close-out)
- §4 Endpoint Definitions — 4-column table, 43 rows, with the 201-create / 200-modify intro paragraph
- §5 Error Code Catalogue — 2-column table, 49 rows. Document ends here; no audit footer.

**Coverage audit (scripted, reported here only)**
- **Contract 1 — Field-Name Coverage: PASS.** 163 required identifiers (143 entity fields + endpoint `input`/`output` identifiers + `limit`/`offset` + nested array keys `through_cents`/`partner_rate`/`through_day`/`refund_pct`) — 0 missing. A broader sweep of every field-shaped token in the scaffold left only 8 non-field artifacts unbackticked: `domain_name`, `http_status`, `rule_id` (scaffold metadata), `program_demand_score` (calculation name), and the four formula-local temporaries `term_days`, `recoup_cap_cents`, `refund_amount_cents`, `holdback_applied` — all rendered as prose ("the term's length in days", "recoupment ceiling", etc.), none persisted or client-visible.
- **Contract 2 — Rule Coverage: PASS.** All 49 error IDs present with HTTP statuses matching the scaffold exactly (0 mismatches, 0 dupes). §2.5 enumerates all 49 validations in exact scaffold priority order with the correct `error_id` at each position and each rule's `applies_to` scope named. Both `concurrency_rules` (`expected_partnership_version`, `ERR_STALE_PARTNERSHIP_VERSION`/412 on terms amendment and statement creation) are documented in §2.6. All 8 state machines: every state name and every action/trigger token appears (0 individual states missing). All 10 calculations covered with their constants, rounding modes, pinned orders and sibling-variant asymmetries — including the once-only modality factor, per-line-then-sum tier rounding, floor on the recoupment and partner-obligation caps, inclusive vs. exclusive threshold comparisons, and the recompute-reversal semantics. All 43 endpoints' `side_effects` reflected, including both multi-hop cascades with their hop causality. Endpoint role lists in §4 match the scaffold on all 43 rows.
- **Contract 3 — §3 Path Purity: PASS.** 1003 backticked tokens in §3: 0 contain `/`, 0 begin with an HTTP method, 0 bare method words anywhere in §3 prose, 0 unbackticked path-like strings.

The two withheld design YAMLs were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 6: Generate implementation — 2026-09-02T08:10:00.000Z

Implementation is complete, verified end-to-end, and all test servers I started have been stopped.

## Files written
Root: `workspace/implementation/` (27 files, ~3,644 lines)

- **Boot**: `start.sh` (guarded `pip install` → `exec python3 app.py`), `requirements.txt` (`Flask==3.0.3`), `app.py` (`create_app()`, envelope error handlers for `ApiError`/404/405/500, global `RLock` per request, `PORT` env default **10000**, bind `0.0.0.0`)
- **Core**: `db.py` (in-memory `Store` of 11 dicts + logical clock, id/seq minting, version bump, collection helpers), `errors.py` (all 49 error ids → HTTP status + default messages), `response.py` (meta/response_type/data envelope), `validation.py` (declarative `Field` specs, unknown-field rejection, date-pair rules, pagination/enum filters), `middleware.py` (auth, action-role map, `PartnerAccountLead` entity-backed scope), `serializers.py` (explicit field tuples per entity), `constants.py` (enums, defaults, calculation constants, action→role maps)
- **Services**: `money.py` (Decimal ROUND_HALF_UP + the two explicit floors), `derive.py` (all aggregate recomputation — never incremental), `demand.py` (dual-variant demand score), `settlement.py` (recognition, pinned per-line marginal tier walk, waterfall), `cascades.py` (Cascade A wind-down fan-out, Cascade B withdrawal, statement staling, teach-out liability waterfall, counselor performance run)
- **Routes** (9 blueprints): `partnerships.py`, `programs.py`, `courses.py`, `counselors.py`, `leads.py`, `enrollments.py`, `statements.py`, `teachout.py`, `clock.py`, plus `common.py` (fetch-or-404 helpers, pagination-before-existence listing)

## Endpoint count
**43** routes registered, matching the SCAFFOLD `endpoints:` list exactly (verified by diffing the live `url_map` against the scaffold).

## Coverage audit
- **Validations**: all 49 priorities implemented in ladder order (auth 1-5 → existence 6-14 → scope/SOD 15-16 → OCC 17 → state 18-25 → business safety/referential/temporal/constraint/fiscal 26-49). Verified programmatically that **all 49 error ids are actually raised** in route/service code (none merely declared in `errors.py`).
- **Calculations**: all 10 (`program_demand_score` both variants, `recognized_tuition_revenue`, `partner_share_gross`, `net_remittance_payable`, `withdrawal_refund_and_clawback`, `counselor_conversion_performance`, `teach_out_obligation_liability`, `blended_customer_acquisition_cost` incl. the null-on-zero-denominator case, and both reconciliation invariants INV-1 cash / INV-2 marketing envelope).
- **State machines**: all 8 entity machines (Partnership 5-state with the REQUEST_CHANGES cycle, Program 9-state, Course, EnrollmentCounselor's two independent dimensions, Lead, Enrollment, RemittanceStatement fork-join with the STALE↔CALCULATED cycle, TeachOutPlan), plus both cascades and independent statement staling. 11 entities, 6 roles.

## Verification
Two standalone smoke suites both report **all expectations passed**, covering the 401/403/400/404/409/412/422 ladder, both cascades, the fork-join settlement with staling + RECALCULATE, successful REMIT (holdback accrual, unrecouped reduction), holdback consumption at plan certification with liability conservation (`holdback + partner_obligation + residual == teach_out_cost`), FEE_FOR_SERVICE gating and `ERR_FEE_STRUCTURE_MISMATCH`, `PATCH /terms` under OCC, `ERR_CIP_EXCLUSIVITY_CONFLICT`, enrollment cap, demand-score thresholds, and pagination bounds. Hand-checked figures matched (e.g. 27/90 inclusive-day straight-line → 3,600,000 recognized → 2,070,000 share at 57.5% → floor(×0.15)=310,500 recoupment → 87,975 holdback → 1,671,525 net; blended CAC 2,000,000/2 = 1,000,000).

**Boot confirmed**: `bash start.sh` on a fresh process serves `GET /partnerships` → 200 with an **empty** `data: []`, `total_count: 0`, and the clock at the default `2026-08-01T00:00:00.000Z` — nothing is seeded or persisted, so per-test-server isolation is safe. `python3 -m compileall` clean; no `__pycache__` left behind. Did not read `test_helpers/`, `test_suite/`, either difficulty/corner design file, or any sibling task directory.

## Step 5: Generate unit tests — 2026-09-02T08:40:00.000Z

Done. Queue B is complete; the suite is finished, verified, and the scratch tooling is removed.

## Files written
Infrastructure — `test_helpers/`: `__init__.py`, `constants.py`, `types.py`, `api_errors.py`, `test_users.py`, `api_client.py`, `factories.py`, `fixtures.py`, `assertions.py`

Tests — `test_suite/`: `conftest.py`, plus queue A `test_01_demand_score_dual_variants.py` … `test_10_conserved_ledgers.py` and queue B `test_20_entities.py`, `test_21_state_machines.py`, `test_22_calculations.py`, `test_23_validations.py`, `test_24_errors.py`, `test_25_endpoints.py`, `test_26_rbac.py`, `test_27_cross_cutting.py`, `test_28_consistency_model.py`

## Counts
- **109 tests collected** (`pytest --collect-only`): queue A 37, queue B 72.
- Queue B per file: entities 12, state_machines 10, calculations 6, validations 20, errors 10, endpoints 4, rbac 5, cross_cutting 4, consistency_model 1.

## Coverage audit (scripted against both yamls)
- Queue A: 18 instances, every one carries ≥2 tagged tests (37 tags) — no shortfall.
- Queue B: 84 instances, 11 are `excluded_because` stubs (not translated; each cross-referenced difficulty instance resolves and is covered in queue A). Of the 73 non-stub instances, 72 have a test; 1 skipped.
- No untagged tests, no dual tags, no tag pointing to a non-existent instance, no unknown tags.
- PRD citation gate: `total=223 bad=0` (every `PRD: "…"` verbatim in `workspace/PRD.md`). No test file mentions the scaffold or any scaffold section. pyflakes clean; all modules import.

## Instances skipped
- `Corner/cross_cutting_complexity_layers/program_enrollment_counters_reconcile_across_activation_and_withdrawal` — the design's headline assertion is `total_enrollment_count == 1` after a withdrawal ("monotonic history counter"). PRD §3.2 defines that counter as "counts those in `ENROLLED`, `ACTIVE` or `COMPLETED`", which excludes `WITHDRAWN`, and §3.8 hop 1 recomputes only `active_enrollment_count`. The PRD therefore derives 0, contradicting the instance's claim, so the instance was dropped rather than inverted.
- The 11 stub instances (by contract, not translated).

## PRD-vs-design adjustments applied (PRD is authoritative)
1. Statuses corrected: `ERR_SEGREGATION_OF_DUTIES` 403, `ERR_TEACH_OUT_OBLIGATIONS_UNMET` 409, `ERR_CONTRACT_TERM_EXPIRED` 409 (design yaml said 409/422/422).
2. Header name `X-User-Role` (design recipes say `X-Role`).
3. `faculty_reviewer_note` (undocumented field → would trip `ERR_INVALID_REQUEST` at ladder item 4) replaced with the required `faculty_approver_name`, so the intended 403/422 is the uniquely-derived outcome.
4. `open_statement_count` asserted through the revenue-summary read, not as a Partnership field.
5. Partnership `version` also advances on Program creation, so chains read versions live; in `partnership_version_increments_on_every_successful_write` the sequence asserted is registration 1 → SUBMIT 2 → EXECUTE 3 → program create 4 → amendment 5 → statement cut 6 (design's 3/4/5 ignored the program-create increment), with the whole child chain (course/scope/launch/lead/enroll/payment) proven not to advance it.
6. Queue A `blended_cac…` kept `prior_year_inquiry_volume` 1750 (design's 1740 yields confirmed 61.90 and cannot be approved).
7. Assertions omitted as not uniquely derivable: DRAFT `marketing_budget_remaining_cents == 4000000`; post-conversion `active_enrollment_count == 0` (PRD §3.6 says it increases by one).

## Step 7: Run tests and iterate — 2026-09-02T13:46:13.000Z

Resumed session. Step 7 re-run to completion per the resume protocol (Step 7 always runs).

### Outcome: CLEAN — all 8 rounds `passed == total`

```
attempt 1 start 13:37:06 load1=77
attempt 1 end   13:42:18 DIRTY 109/109 109/109 109/109 109/109 108/109(e=1) 109/109 109/109 109/109 realfail=NONE
attempt 2 start 13:42:18 load1=28
attempt 2 end   13:46:13 CLEAN 109/109(f=0,e=0) x8  realfail=NONE
ALL_ROUNDS_GREEN
```

`results.{1..8}.json` on disk are the attempt-2 CLEAN set: 109/109, failed=0, errors=0 in every round.

### Iterations run: 0 corrective iterations (0 diagnostic fix cycles)

No test was deleted, no assertion weakened, no `test_suite/`, `test_helpers/`, or `implementation/` file was edited in this session.

### Adjudication of the inherited DIRTY sweep

The prior session's sweep (attempt 1, 10:12–10:31) looked catastrophic — 51–83 of 109 passing, 26–58 errors per round, and one nominal `realfail`
(`test_restated_waterfall_pins_the_adjustment_delta`). All of it was infrastructure noise, not an artifact defect:

- That sweep started at **load1=308** on a 32-core box (~10x oversubscription); 105 of 109 distinct tests errored in at least one round.
- The single `realfail` was itself
  `requests.exceptions.ConnectionError: ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))` —
  a transport death, not a tripped assertion. There was no assertion failure anywhere in the eight result files.
- Re-running the identical sweep at load1=28 produced 109/109 in all 8 rounds with zero errors, confirming the diagnosis. Per the
  load-induced-failure guidance, nothing was "fixed" because nothing was broken.

Diagnostic protocol STEP 1/2/3 were therefore never entered: the union failure set at low load is empty.

### Method note (retry driver)

`workspace/sweep_driver.sh` (inherited, retuned this session) runs the 8-round parallel sweep under `setsid`, waits for a quiet window
before each attempt, and retries until a fully green sweep. Thresholds were retuned from `LOAD_TARGET=70 / FALLBACK=120 / PATIENCE=360`
(3h of waiting, which would have idled indefinitely as ambient load oscillated 65–95) to `LOAD_TARGET=100 / FALLBACK=160 / PATIENCE=40`.
Judgement call, made without escalation per the autonomy directive: load ~80 is ~4x better than the 308 that caused the collapse, so it
was worth attempting rather than waiting hours for an unattainably quiet host. It succeeded on the second attempt.

Operational note for future resumes: `pgrep -f` / `pkill -f <pattern>` inside a Bash tool call **matches the calling shell's own command
line** and self-kills the call (observed twice: exit 144, then a silent no-output kill). Use a bracket-escaped pattern —
`pgrep -f 'sweep[_]driver'` — which matches the target but not the literal in your own argv.

### Fixes applied
- `test_suite/`: none.
- `test_helpers/`: none.
- `implementation/`: none.
- Tests deleted: none. (Step 5 collected 109; 109 collect and pass now. No `pytest.mark.skip` / `xfail` anywhere in `test_suite/`.)

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T13:50:00.000Z

Skip condition met. Step 7 produced 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes, so there is
no `<step_7_diff>` to scope Step 8's edits to, and no PRD-silence site that Step 7 exposed. `workspace/PRD_FINALIZED.md` is therefore not
produced; Step 9 starts from `workspace/PRD.md`.

Evidence that this holds for the task's whole history, not just this session (the earlier session never wrote a Step 7 entry, so the
filesystem was audited directly):

- **0 implementation fixes.** No file under `workspace/implementation/` has an mtime later than the Step 6 generation window
  (latest is `app.py` / `routes/__init__.py` at 07:55; Step 6 logged at 08:10). Nothing in `implementation/` was ever touched by a fix cycle,
  so there is no site where the implementation pinned a behavior the PRD left open as a result of iteration.
- **0 deletions.** Step 5 reported 109 tests collected; 109 collect and pass today. No `pytest.mark.skip` / `xfail` in `test_suite/`.
- Two test-side files (`test_helpers/fixtures.py` 08:31, `test_suite/test_05_transitive_cascades.py` 08:57) carry mtimes past the bulk
  generation window and may have received refinements from the earlier session. Their test count and design tags are intact (test_05 has 4
  tests, all tagged to two `Difficulty/transitive_cascade` instances). Even read as Step 7 test-side fixes, Step 8's own method classes
  fixture repairs as "not every item is a PRD silence — some are pure fixture bugs", and with 0 implementation fixes they yield no PRD edit
  under Step 8's HARD SCOPE rule.

Judgement recorded per the autonomy directive: fabricating a `<step_7_diff>` to justify running Step 8 would licence PRD edits that trace to
nothing, which is exactly what the HARD SCOPE rule forbids. Step 9's full PRD-vs-`implementation/` scan is unconditional and subsumes the
coverage Step 8 would have contributed.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T14:04:00.000Z

Done. `PRD_COMPLETED.md` is written with 61 minimal in-paragraph edits, all matched uniquely (script asserted exactly-one match per replacement). No sections, headings, or catalogue rows were added or removed (26 headings, 96 table rows unchanged).

## Metrics
| | PRD.md | PRD_COMPLETED.md | delta |
|---|---|---|---|
| lines | 479 | 481 | +2 |
| chars | 101,416 | 112,446 | **+11,030** |
| bytes | 101,853 | 112,960 | +11,107 |

Changed lines: 55 (several lines carry more than one edit). The +2 lines are the blank line and single trailing sentence appended after the §5 error table.

## Counts
- **ambiguity-pins: 47**
- **mismatch-revisions: 14**

## Changes

- §2.1 — insert — ambiguity — whitespace-only `X-User-ID`/`X-User-Role` counts as empty for `ERR_MISSING_AUTH_HEADERS` — middleware.py:15
- §2.1 — insert — ambiguity — partner list scoping is a silent narrowing, an explicit conflicting `partnership_id` is a scope violation, and an unknown `program_id` yields an empty page — middleware.py:47, routes/courses.py:67
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus twenty upper-case alphanumerics — response.py:13
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time — response.py:17
- §2.3 — insert — ambiguity — `limit`/`offset` must be bare integer literals; undeclared enum filter members are 400; undeclared query params are ignored — validation.py:201,227
- §2.3 — insert — ambiguity — equal `created_at` ties are broken by server insertion order — db.py:146
- §2.4 — insert — ambiguity — `version` advances at most once per entity per request, and an unchanged recomputed value mutates nothing — db.py:108, services/derive.py:114
- §2.4 — insert — ambiguity — the clock accepts any ISO 8601 instant (Z, offset, or naive-as-UTC) and reports both instants at ms precision — routes/clock.py:20
- §2.5 item 4 — insert — ambiguity — the ten action-conditional required fields, empty string as absent, and `window_start`/`window_end` explicitly not an ordered pair — routes/enrollments.py:84, routes/courses.py:123, routes/partnerships.py:209
- §2.5 item 18 — insert — ambiguity — full inventory of what does *not* gate on partnership status — routes/programs.py:100, routes/counselors.py:45
- §2.5 item 19 — revise — mismatch — only `APPLY` (not `CONTACT`/`DISQUALIFY`) requires the program to be `LAUNCHED` — routes/leads.py:137
- §2.7 — revise — mismatch — `marketing_budget_remaining_cents` is held at 0 until `executed_date` is set — services/derive.py:147
- §2.8 — insert — ambiguity — partnership totals are full recomputes from facts, with the three derivation formulas spelled out — services/derive.py:114-157
- §3.1 — insert — ambiguity — `expiry_date` month arithmetic clamps to the last day of the target month — services/money.py:71, services/derive.py:176
- §3.1 — insert — ambiguity — tier/band array validation (non-empty, exact keys, rate in [0,1]) and the absence of sort/unbounded-final checks; `exclusivity_cip_codes` unpatterned — validation.py:50,73
- §3.1 — insert — ambiguity — remaining envelope stays 0 while `executed_date` is null — services/derive.py:147
- §3.1 — revise — mismatch — `wind_down_effective_date` is mandatory on `WIND_DOWN` (was "optional"); notes not persisted — routes/partnerships.py:209
- §3.1 — revise — mismatch — an amendment's remaining-budget recompute still yields 0 pre-execution — services/derive.py:147
- §3.1 — revise — mismatch — revenue summary is available to every role *except* `FacultyChair` (was "any role") — routes/partnerships.py:26
- §3.2 — insert — ambiguity — `required_service_domains` may be empty or repeat, members must be declared domains — routes/programs.py:44,133
- §3.2 — insert — ambiguity — program creation is not screened against `expiry_date` — routes/programs.py:326
- §3.2 — revise — mismatch — revised submit inputs and the new screening score persist only when the 45.00 test passes — routes/programs.py:241
- §3.2 — insert — ambiguity — `demand_score_confirmed` persists only when approval succeeds — routes/programs.py:259
- §3.2 — insert — ambiguity — only `SUBMIT`/`LAUNCH`/`RESUME` require an `EXECUTED` partnership; `revision_note`/`teach_out_reason` not stored — routes/programs.py:221
- §3.2 — revise — mismatch — `blended_cac_cents` starts null, not zero — routes/programs.py:146, services/derive.py:100
- §3.3 — revise — mismatch — `course_code` uniqueness is expected but not enforced — routes/programs.py:346
- §3.3 — insert — ambiguity — cycle detection walks forward from the proposed prerequisite — routes/programs.py:297
- §3.3 — insert — ambiguity — a `START_DESIGN` parent-program breach reports `ERR_COURSE_INVALID_DESIGN_STATE` — routes/courses.py:131
- §3.3 — insert — ambiguity — course `revision_note` accepted but not stored — routes/courses.py:117
- §3.3 — insert — ambiguity — `faculty_approver_name` must be non-empty and is screened before the course lookup — routes/courses.py:123
- §3.3 — insert — ambiguity — `program_id`/`prerequisite_course_id` filters are exact identifier matches — routes/courses.py:67
- §3.3 — insert — ambiguity — `sla_response_hours` is any integer ≥ 0 — routes/programs.py:69,387
- §3.5 — insert — ambiguity — counselor onboarding reads no partnership status — routes/counselors.py:45
- §3.5 — insert — ambiguity — omitted `variable_component_cents`/`variable_basis` default to 0 and `NONE` — routes/counselors.py:114
- §3.5 — insert — ambiguity — only the `QUALITATIVE_MULTI_FACTOR` pairing needs the bundled-services claim — routes/counselors.py:120
- §3.5 — insert — ambiguity — `reviewer_note` accepted but not stored — routes/counselors.py:143
- §3.5 — insert — ambiguity — a program with no `ENROLLMENT_COUNSELING` assignment produces no SLA breaches — services/cascades.py:178
- §3.5 — insert — ambiguity — `downgraded_count` includes the `PROBATION` absorption; the run does not touch the partnership — services/cascades.py:230
- §3.6 — revise — mismatch — marketing `amount_cents` is zero-or-more, not "positive" — routes/programs.py:409
- §3.6 — insert — ambiguity — `reversal_note` must be non-empty and is screened before program lookup — routes/programs.py:412
- §3.6 — revise — mismatch — `prospect_external_id` uniqueness not enforced, and the counselor need not share the program's partnership — routes/leads.py:61,78
- §3.6 — insert — ambiguity — `CONTACT`/`DISQUALIFY` carry no program-state gate — routes/leads.py:137
- §3.6 — insert — ambiguity — `credits_enrolled` may be any integer ≥ 0 — routes/leads.py:161
- §3.7 — revise — mismatch — tuition `amount_cents` is zero-or-more, not "positive" — routes/enrollments.py:122
- §3.7 — revise — mismatch — `credits_completed` is required (not merely accepted); the over-cap 400 runs after the state gate — routes/enrollments.py:84,101
- §3.7 — insert — ambiguity — a `COMPLETE` credit mismatch is `ERR_ENROLLMENT_INVALID_STATE` — routes/enrollments.py:106
- §3.7 — insert — ambiguity — early `withdrawal_date` is 400 after the state gate; `withdrawal_reason` not stored — routes/enrollments.py:113
- §3.7 — insert — ambiguity — no matching refund band yields an applied percentage of 0 — services/cascades.py:63
- §3.7 — insert — ambiguity — the generated refund entry uses `withdrawal_date` as `posted_date`, a null `reference_note`, and is suppressed at zero — services/cascades.py:93
- §3.8 — insert — ambiguity — the overlap screen precedes the period-elapsed screen — routes/partnerships.py:281
- §3.8 — insert — ambiguity — a zero-credit enrollment yields a cumulative milestone figure of 0 — services/settlement.py:59
- §3.8 — insert — ambiguity — the contract-year window is selected by the logical clock's date — services/derive.py:50,154
- §3.8 — insert — ambiguity — the tier-walk starting position is the sum over the partnership's *other* statements in the contract year of this statement's `period_start` — services/settlement.py:165
- §3.8 — insert — ambiguity — no unbounded final tier leaves a remainder unshared; negative lines walk in reverse; zero lines are skipped — services/settlement.py:86
- §3.8 — insert — ambiguity — `RESOLVE` leaves `approved_by_user_id` intact; `adjustment_note` not stored — routes/statements.py:94
- §3.9 — revise — mismatch — `wind_down_effective_date` mandatory and the past-date 400 runs after the state gate — routes/partnerships.py:229
- §3.9 — revise — mismatch — the four plan money buckets initialise to 0, not null — routes/programs.py:480
- §3.9 — insert — ambiguity — only `DRAFT` plans are superseded, so a program can hold several `CERTIFIED` plans — routes/programs.py:466
- §3.9 — insert — ambiguity — a non-`TEACH_OUT` parent program is `ERR_PROGRAM_INVALID_STATE`, after the plan state and before the notice check; `certification_note` not stored — routes/teachout.py:39
- §3.9 — insert — ambiguity — `holdback_applied_cents` is floored at 0 — services/cascades.py:146
- §5 — insert — ambiguity — undeclared path → `ERR_NOT_FOUND` 404; undeclared method → `ERR_METHOD_NOT_ALLOWED` 405 — app.py:40,44

## Notes
- The scale note in the brief (~2500 lines) did not match reality: PRD.md is 479 very long lines, so the char delta is the meaningful measure.
- `workspace/PRD_FINALIZED.md` indeed does not exist; the base was `workspace/PRD.md`.
- Three things I deliberately did **not** write, because impl does not exhibit them: any statement-of-record for `_seq` as a response field (it is stripped by the serializers), any claim that ledger serialisations carry `updated_at`/`version` (they deliberately omit both, which PRD §2.4 already hedges with "most resources"), and any new error-catalogue rows for the transport errors (a trailing sentence keeps the 49-row table intact).
