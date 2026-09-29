# Worklog — task_2646_outfitter_guide_special_use_permit_administration

## Step 1: Create task directory — 2026-09-04T00:10:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2646_outfitter_guide_special_use_permit_administration and its workspace/ subdirectory. Index 2646 was pre-assigned by the orchestrating prompt (no ./tasks/ scan performed, per instruction, to avoid collision with concurrent pipelines).

## Step 2: Generate scaffold (subagent) — 2026-09-04T02:46:00.000Z

All three scaffold artifacts are complete and lint-clean.

Files:
| Path | Lines |
|---|---|
| SCAFFOLD.yaml | 3648 |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 3557 |
| SCAFFOLD_CORNER_DESIGN.yaml | 4795 |

SCAFFOLD.yaml contains zero occurrences of scaffold_difficulty_design / scaffold_corner_design; each design file has its single mandated top-level key; all three parse as YAML.

Lint verdict:
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2646_outfitter_guide_special_use_permit_administration/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2646_outfitter_guide_special_use_permit_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2646_outfitter_guide_special_use_permit_administration/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    74
  §1.1 entities declared:     15
  §1.8 instances scanned:     31
  §1.9 instances scanned:     45
  Calls scanned (§1.8+§1.9):  1496

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Design summary:

Profile — api_prefix: /osup, difficulty expert_plus; entity_topology flat; state_machine_shape parallel; role_model segregation_of_duties; consistency_model immediate; complexity_layers [optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy]. Roles: OutfitterRepresentative (entity_backed:Outfitter), PermitSpecialist, AuthorizedOfficer, ProgramAdministrator.

Surface — 15 entities (UseArea, NeedsAssessment, Prospectus, Outfitter, PermitApplication, Permit, OperatingPlan/section rows, Guide, GuideAuthorization, InsuranceCertificate, Bond, TripUseReport, FeeAssessment, PerformanceEvaluation, NoncomplianceAction), 74 endpoints, 13 state machines, 16 calculations, 64 validations/errors, 2 OCC concurrency rules.

Core mechanics — capacity determination routes an application to DIRECT_ISSUE vs PROSPECTUS_QUEUED depending on allocatable days; prospectus scoring is weighted .30/.30/.20/.20 with a need_match term and a PRELIMINARY/FINAL dual variant that can flip the rank; the award is a selector (rank DESC, created_at ASC tie-break, empty-pool error) gated on expected_use_area_version. Fees are a percentage of adjusted gross revenue across a 300/400/500 bp bracket ladder with a 15% deduction cap and a 30,000-cent minimum, computed under two variants (PROVISIONAL_PER_REPORT rounds per report from the cumulative prior AGR; FINAL_AGGREGATE splits the season total and rounds once). Guide authorizations freeze min(UseArea.max_clients_per_guide, Guide.base_client_capacity) so live and frozen capacity legitimately diverge. Noncompliance points (2/5/10, 1095-day rolling window) drive PROBATION at 5 and NONCOMPLIANT at 12, suspension days = 30 × (1 + upheld MAJOR count), and reinstatement walks a pinned four-gate ladder (points → insurance → bond → fee). Transfers require COMPLIANT status, zero suspensions and at most one holder change.

§1.8 (31 instances) — two instances for each of the nine hard-reasoning rules plus extras, covering dual-variant fee and scoring divergence, four- and five-hop cascades (screening reroute, point-threshold suspension, the daily sweep's guide-lapse → authorization → ratio chain), validation-priority conflicts across tiers, boundary arithmetic at every constant, and cross-entity state dependencies.

§1.9 (45 instances across all nine guide sections) — entities 11; state_machines 7 real + 8 stubs; calculations 6 + 8; validations 5 + 4; endpoints 5 + 1 (standard_crud, action_endpoint, cross_reference_link, computed_read, conditional_action); errors 3 + 1; rbac 3 (all segregation_of_duties: role-exclusive denials, foreign-holder / unknown-role boundary, same-user-id review-then-approve); complexity_layers 4 + 3 (both mandated OCC stale-version tests — ERR_STALE_USE_AREA_VERSION on award and ERR_STALE_PERMIT_VERSION on amend, each proving the failed attempt consumes no version and the replay increments by exactly one; a cascade partial-failure instance showing a refused suspension writes none of its four hops; the selector tie-break; dual-variant stubs); consistency_model 1 (immediate — accept synthesizes the FeeAssessment and re-derives service_days_used_ytd / fee_delinquent / PROBATION visibly in the same response and next read).

All 64 declared error ids are triggered by at least one §1.8 or §1.9 instance (verified programmatically), every stub cites a §1.8 instance that exists by name, no instance carries keys outside the §1.9 schema, and instance names are unique across the union of both design files.

Two notes for downstream: (1) selector_policy is a sanctioned §0.2 layer but the claim-extraction guide's complexity-layers table has no row for it, so its claim_type is the layer name by the table's own convention; (2) ERR_FEE_BALANCE_OUTSTANDING is unreachable through the holder-change path (an outstanding balance forces PROBATION, so tier-11 ERR_TRANSFER_NOT_PERMITTED wins) and is therefore covered on the reinstatement ladder instead.

## Step 3: Copy shared files — 2026-09-04T02:47:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes). Task dir still contains SCAFFOLD.yaml + both design files + worklog.md (verified after Step 2 — no wipe occurred).

## Step 4: Generate PRD (subagent) — 2026-09-04T03:08:00.000Z

Output: workspace/PRD.md — 484 lines / 119,077 bytes, built by 9 incremental `cat >>` appends with `wc -l` verification after each. Written from SCAFFOLD.yaml only; SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml and all sibling task directories were never opened.

Section list:
- # Outfitter & Guide Special Use Permit Administration API — Product Requirements Document
- ## 1. Introduction
- ## 2. Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim fixed block, byte-identical, confirmed by substring match) · 2.3 Pagination · 2.4 Common Record Properties, Timestamps and the Logical Clock · 2.5 Rejection Precedence · 2.6 Optimistic Concurrency on the Allocation and the Fee Basis · 2.7 The Service-Day Ledger and the Posture of an Area · 2.8 Money, Scores and Rounding · 2.9 Derived Signals and Cascade Discipline · 2.10 Resolving Nested Paths and Sub-Resource Collections
- ## 3. Business Logic & Workflows — 3.1 Setting the Program Up: Areas, Public Need, Outfitters and Guides · 3.2 Application Intake and the Capacity Screen · 3.3 Competitive Solicitation: Scoring, Ranking and Award · 3.4 Issuance, and the Long Walk to an Operable Permit · 3.5 The Annual Operating Plan Review Cycle · 3.6 Financial Assurance and the Authorized Guide Roster · 3.7 Reporting Actual Use, and the Two Ways to Compute a Fee · 3.8 Performance Rating, Enforcement, and the Compliance Dimension · 3.9 Renewal, Transfer of the Holder, Expiry and the Nightly Sweep
- ## 4. Endpoint Definitions — intro + 4-column table, 74 rows (verified count)
- ## 5. Error Code Catalogue — 2-column table, 64 rows (verified count)

Tail confirmation (subagent, independently re-verified by the orchestrator): document ends at a completed section boundary — last line of §5's table is `| ERR_DEDUCTIONS_EXCEED_CAP | 422 |` followed by a single trailing newline. No truncation, no content after §5.

Hard Contract 1 — Field-Name Coverage: PASS. 153 required identifiers (140 entity field names + all endpoint input body fields, query params and {id} path params, deduplicated); 153 present verbatim in backticks; 0 missing.

Hard Contract 2 — Rule Coverage: PASS. All 64 error IDs appear in §1–§4 prose, not merely in the §5 table (verified programmatically). All 86 declared enum member values appear in backticks; all 13 state machines' state names and all 57 transitions are documented (35 without a literal arrow glyph but each described in prose — supersession, expiry, revert and cascade edges). Both concurrency_rules OCC fields documented with their 412 errors and the "why not a status precondition" rationale. All 16 calculations translated to prose including both dual variants of permit_fee_assessment and of the prospectus score, the pinned six-step rating order, both conservation identities, and the derivation-order rules. All 64 validations covered, plus the three pinned priority-conflict outcomes and both intra-tier orderings (priority 12 on activate/reinstate; priority 8 on guide authorization, including that ERR_GUIDE_NOT_QUALIFIED is reachable only for a guide awaiting first qualification). No pseudocode, no round_half_up/SUM(/IF fragments, no scaffold section references, no calculation identifiers, no fuzzy quantifiers (all verified by grep).

Hard Contract 3 — §3 Path Purity: PASS. 1,154 backticked tokens between `## 3.` and `## 4.`; 0 begin with /, 0 are bare HTTP methods, 0 combine method+path; 0 raw /osup occurrences anywhere in §3.

Three scaffold contradictions resolved (recorded so the implementer's reading is deterministic):
- unallocated_service_days is floored at zero (entity definition), deliberately contrasted with available_service_days, which the scaffold explicitly allows to go negative.
- qualify accepts a TRAINEE (endpoint text + the priority-8 rule's applies_to scope); ERR_GUIDE_LEVEL_INELIGIBLE is reachable only at guide authorization.
- Insurance supersession uses the endpoint's containment rule (same coverage_type AND full interval containment), not the state machine's blanket same-type rule, since ERR_INSURANCE_COVERAGE_GAP requires contiguous same-type ACTIVE certificates to coexist.
- Also noted: the PerformanceEvaluation recording endpoint is AuthorizedOfficer-only per §1.5, so evaluator_user_id is documented as the acting officer's X-User-ID rather than the entity description's "PermitSpecialist".

Difficulty instruction ("Generate task harder than expert level!") was NOT forwarded to the doc generator and does not appear in PRD.md.

## Step 5: Generate unit tests (subagent) — 2026-09-04T05:32:00.000Z

Orchestrator note: Steps 5 and 6 were intended to launch in one message. They were launched in two consecutive messages ~30 seconds apart; the impl generator's physical isolation still held because `ls -d workspace/test_*` and the task-root test dirs were both still absent when the impl agent started (verified at 03:13Z — only workspace/implementation/ existed). Both agents also carried explicit textual isolation constraints.

Subagent summary (verbatim):

Test infrastructure and test suite are complete.

Output directories:
- test_helpers/
- test_suite/

`ls -d .../workspace/test_* 2>/dev/null` finds nothing (exit 2). Nothing was read or written under workspace/implementation/, and no sibling task directory was touched.

test_helpers/ (2540 lines)
| file | lines |
|---|---|
| __init__.py | 46 |
| api_client.py | 407 |
| api_errors.py | 167 |
| assertions.py | 317 |
| constants.py | 95 |
| factories.py | 278 |
| fixtures.py | 682 |
| test_users.py | 80 |
| types.py | 468 |

test_suite/ (9753 lines, 109 tests)
| file | lines | tests |
|---|---|---|
| conftest.py | 61 | — |
| test_01_service_day_ledger.py | 669 | 11 |
| test_02_registration_and_request_shape.py | 319 | 5 |
| test_03_server_owned_fields_and_initial_states.py | 489 | 5 |
| test_04_public_need_and_the_screening_fork.py | 429 | 6 |
| test_05_guide_capacity_formula.py | 418 | 6 |
| test_06_guide_authorization_gates.py | 374 | 5 |
| test_07_prospectus_competition.py | 519 | 6 |
| test_08_permit_terms_and_holder.py | 434 | 4 |
| test_09_permit_dimensions_and_terminal_states.py | 323 | 3 |
| test_10_activation_gates.py | 335 | 3 |
| test_11_assurance_intervals_and_bond_clamps.py | 318 | 3 |
| test_12_operating_plan_review.py | 477 | 4 |
| test_13_use_reports_and_periods.py | 905 | 9 |
| test_14_fee_variants.py | 305 | 4 |
| test_15_fee_cascades.py | 469 | 4 |
| test_16_performance_evaluation.py | 255 | 3 |
| test_17_fee_boundaries.py | 561 | 6 |
| test_18_compliance_cycle_and_points.py | 325 | 4 |
| test_19_suspension_cascade_and_the_window.py | 380 | 4 |
| test_20_priority_conflicts.py | 511 | 6 |
| test_21_state_and_gates.py | 450 | 4 |
| test_22_roles_and_listings.py | 427 | 4 |

Coverage tally:
- Queue A (§1.8 difficulty): 31 / 31 instances, every one with >=2 tests (difficulty instances with <2 tests: []).
- Queue B (§1.9 corner): 45 / 70 instances — that is all 45 non-stub instances, each with >=1 test.
- Every test carries exactly one `Design:` line as its final docstring line.

Gates (all green):
- python3 -m pyflakes test_suite/*.py test_helpers/*.py -> exit 0.
- Citation checker (each `PRD §x.y: "…"` quote matched verbatim against workspace/PRD.md, whitespace-normalised) -> 109 tagged tests, 0 problems.
- Tag checker against both design yamls -> 31/31 difficulty, 45/70 corner, no <2 difficulty instances.
- All 63 distinct api_client.<method> uses and all `from test_helpers import …` names resolve (hasattr sweep, no misses).
- pytest test_suite --collect-only -q -> 109 tests collected, no collection errors.

Skipped instances: the 25 queue B entries carrying `excluded_because:` were not translated, per the design contract — each is self-declared redundant with a §1.8 instance already covered (e.g. suspension_cascade_reaches_the_outfitter_status -> noncompliance_points_suspension_cascade_depth_five; fee_brackets_tested_at_each_tier_boundary -> fee_tier_one_ceiling_inclusivity_boundary; pinned_cross_tier_conflicts_return_the_higher_tier_error -> suspended_permit_beats_service_day_overage). No non-stub instance was skipped for lack of PRD coverage.

Three design-vs-PRD conflicts were resolved in favour of the PRD rather than weakened: (1) the A14 collision test asserts the cumulative service-day cap at acceptance, where PRD §3.7 places it, not at filing as the design text implies; (2) denial_reason_code is a free string in SCAFFOLD, so it cannot trip a tier-5 shape error ahead of the tier-7 state error; (3) B18's literal "version is still 3/4" became capture-then-compare, which is what §2.4 actually guarantees.

## Step 6: Generate implementation (subagent) — 2026-09-04T05:32:00.000Z

Subagent summary (verbatim):

Finished the Python + Flask implementation at workspace/implementation/.

Files (4,103 lines total, all written incrementally in <=200-line chunks):
| File | Lines |
| --- | --- |
| requirements.txt | 1 |
| start.sh | 10 |
| app.py | 62 |
| store.py | 232 |
| errors.py | 89 |
| envelope.py | 87 |
| security.py | 50 |
| shapes.py | 170 |
| calc.py | 648 |
| serialize.py | 292 |
| routes/__init__.py | 24 |
| routes/common.py | 46 |
| routes/setup.py | 236 |
| routes/applications.py | 393 |
| routes/prospectuses.py | 239 |
| routes/permits.py | 236 |
| routes/plans.py | 215 |
| routes/guides.py | 219 |
| routes/assurance.py | 146 |
| routes/reports.py | 334 |
| routes/enforcement.py | 226 |
| routes/ops.py | 148 |

Endpoint count: 74 — url_map diffs byte-identically against the 74-row PRD §4 table (method + normalized path), no extras, no gaps.

Structure notes:
- State machines live in the route modules as explicit ordered guards following PRD §2.5's 12 tiers (auth -> authz -> existence -> ownership -> shape -> OCC -> state -> safety -> referential -> temporal -> structural -> fiscal). Shared multi-record transitions are factored into calc.py: suspend_permit, close_out_permit (revoke/expiry/succession-close tail), revoke_roster, close_settled_assessments, derive_compliance (the one rule for the compliance_status dimension, with the NONCOMPLIANT-while-ACTIVE -> 30x(1+upheld majors) suspension cascade).
- Calculations are all full-recompute aggregates in calc.py using Decimal + ROUND_HALF_UP (never float): area ledger/posture, the dual fee variants (PROVISIONAL_PER_REPORT rounds per report on the opening cumulative bracket, FINAL_AGGREGATE splits the season total and rounds once), dual prospectus scoring (preliminary/final), the six pinned performance-evaluation steps (provisional_band from raw, published rating from weighted), guide capacity, bond requirement, plan completeness.
- OCC: exactly two tokens, checked at tier 6 (before state, per §2.5's numbered list, which overrides the narrative order in §3.3/§3.7) — expected_use_area_version on prospectus award (ERR_STALE_USE_AREA_VERSION 412) and expected_permit_version on use-report amend (ERR_STALE_PERMIT_VERSION 412). A rejected check writes nothing: before_request snapshots the whole store (deepcopy) and every error handler rolls back, so cascades are atomic. store.touch() de-duplicates per request so a row's version advances at most once. PerformanceEvaluation is inserted with common=False, so it carries only id/created_at — no updated_at, no version.
- Storage is in-memory dicts only; nothing is seeded (verified: every collection reports total_count 0 on a fresh boot).

start.sh contract confirmed: reads $PORT (app.py: int(os.environ.get("PORT", "10000"))), binds 0.0.0.0, and runs in the foreground via exec python3 app.py. The pip install is guarded by an `import flask` probe so per-test reboots don't contend.

Verification performed: booted on random high ports (27641/27655/27672/27691/27703) and ran four scripted flows plus two blanket probes, all killed afterwards by exact pid (no broad pkill). Full direct-award lifecycle; competitive path with oversubscription re-route, prospectus award incl. stale-412, activation blocker ladder, suspend/reinstate, transfer blocked, revoke releasing the ledger; remaining endpoints incl. prequalification, cancel, plan sections/reject/refile, certifications, authorization revoke->reauthorize, assurance/evaluation/action lists, cure, points-threshold cascade, successful holder-change. Blanket probes: all 74 routes x 4 roles with bogus ids/empty bodies -> 0 responses >= 500; garbage-typed bodies, malformed JSON, and out-of-range limit/offset all return ERR_INVALID_REQUEST 400.

Isolation respected: nothing under test_suite/, test_helpers/, the two SCAFFOLD_*_DESIGN.yaml files, or any sibling task dir was read; all writes landed in workspace/implementation/.

## Step 7: Run tests and iterate (subagent) — 2026-09-04T05:54:00.000Z

Orchestrator verification: independently re-read all 8 workspace/implementation/results.$i.json — every one reports passed=109, total=109, failed=0, all written at 05:46Z. Sweep artifacts confirmed present (not a phantom clean sweep).

Subagent summary (verbatim):

All 8 rounds are green. Iterate-until-green loop complete after 2 iterations.

Iterations run: 2 (iteration 1: 98/109 in every round, fully deterministic — no flakiness or sweep reaping; iteration 2: 109/109 in all 8 rounds)

Tests deleted: none. No failure bottomed out in a full-sentence PRD silence (STEP 1a) or a collapse pattern (STEP 1b) that required removing a whole test. One test hit STEP 1c and was split rather than deleted (below).

Fixes applied to test_helpers/:
- test_helpers/fixtures.py — setup_issued_permit(): added `application = read_application(application["id"])` after issue_permit(...), because the fixture was handing back the pre-issuance snapshot (DIRECT_AWARD_PENDING) while PRD §3.4 says "The application moves to `PERMIT_ISSUED`" — the implementation was already correct.

Fixes applied to test_suite/:
- test_14_fee_variants.py — corrected final["balance_due_cents"] from 5_000 (the finalization delta) to 131_002. PRD §3.7: "balance_due_cents is assessed_fee_cents less paid_to_date_cents floored at zero", and the test's own neighbouring paid_to_date_cents == 0 / credit_balance_cents == 0 assertions force 131,002. Arithmetically wrong expectation, not a weakened assertion.
- test_17_fee_boundaries.py — _reporting_permit() gained area_overrides/outfitter_overrides pass-through; the second permit in test_the_two_variants_agree_past_the_ceiling_and_differ_by_a_thousand_on_it now uses area_code "BRW-17" / ein "410001700". The test previously built two permits with the same unique keys and died in setup on ERR_INVALID_REQUEST.
- test_06_guide_authorization_gates.py — STEP 1c partial-coverage split in test_a_second_immediate_sweep_moves_nothing_and_holds_the_derived_pair: replaced only `assert permit["compliance_status"] == "PROBATION"` (after the second, idle sweep) with assert_compliance_derivation(permit); added that name to the barrel import. Reason: §3.8 gives the compliance derivation exactly three terms (points, insurance_current, fee_delinquent) and re-derives after any change to them, while §3.9's guide-lapse cascade writes PROBATION for a capacity shortfall as an event-scoped side effect. Whether that PROBATION survives a later idle re-derivation is not uniquely determined (COMPUTED-FIELD SILENCE on persistence). Every other assertion was kept, including PROBATION after the first sweep (verbatim-covered by the §3.9 cascade paragraph and still asserted in the sibling test), all six zero counters, ACTIVE, capacity 8, unchanged guide version, and the roster statuses.

Fixes applied to implementation/:
- serialize.py — USE_AREA_FIELDS was missing allocatable_service_days, causing KeyError in 5 tests. Required by PRD §2.7 ("republishes all four terms — allocatable_service_days, ...") and §3.1 ("A single area read exposes all four allocation figures").
- calc.py — recompute_area() now persists area["allocatable_service_days"] from the ledger (it was computed but never written back).
- routes/setup.py — create_use_area(): seeds allocatable_service_days on insert; and added the missing season_close_date < season_open_date -> ERR_INVALID_REQUEST check, required verbatim by §2.5 tier 5 ("every date pair correctly ordered").
- routes/reports.py — record_payment(): state gate narrowed from `status not in ("PROVISIONAL","FINAL")` to `status == "CLOSED"`. §3.7 assigns ERR_FEE_ASSESSMENT_CLOSED to a payment "against a closed assessment" only; a PAID assessment has balance 0, so the verbatim balance rule (ERR_PAYMENT_EXCEEDS_BALANCE) is what rejects it. Externally observable behaviour for PAID is unchanged apart from the correct error_id.

Storage remains in-memory only — no sqlite/file/tmp writes and no startup seeding anywhere in implementation/ (verified by grep).

Final sweep evidence (workspace/implementation/results.$i.json):
| round | passed / total |
|---|---|
| 1 | 109 / 109 |
| 2 | 109 / 109 |
| 3 | 109 / 109 |
| 4 | 109 / 109 |
| 5 | 109 / 109 |
| 6 | 109 / 109 |
| 7 | 109 / 109 |
| 8 | 109 / 109 |

Step 8 gate: Step 7 applied 4 implementation/ fixes and 4 test-layer fixes, so the skip condition does NOT apply — Step 8 runs.

## Step 8: Finalize PRD (subagent) — 2026-09-04T06:04:00.000Z

Orchestrator verification: PRD.md 484 lines / 119,093 bytes vs PRD_FINALIZED.md 484 lines / 120,730 bytes; exactly 5 lines differ (not byte-identical, so the pass really ran); tail still ends at the completed §5 error table.

Subagent summary (verbatim):

All edits applied and verified. Line counts identical (484 -> 484), byte delta +1,637 (+1.37%), file still ends at the completed §5 error table; exactly 5 lines differ.

Changes:
- §3.1 (use-area read) — revise — named the four allocation figures explicitly (allocatable_service_days, committed_service_days, pending_service_days, available_service_days) plus demand_ratio/allocation_posture, and stated they travel on the listing and the creation response too — serialize.py:29-46, routes/setup.py:63,71-72,79,92, calc.py:137-147
- §3.1 (opening an area) — revise — pinned the season window's ordering as weak: same calendar day admissible, close before open is ERR_INVALID_REQUEST — routes/setup.py:44-45
- §3.1 (guide-lapse chain) — insert — noted the capacity-shortfall PROBATION is event-scoped, lands only on a still-COMPLIANT permit, and is recomputed away by the next re-derivation — routes/ops.py:133-140
- §3.7 (payments) — revise — replaced "accepted while PROVISIONAL or FINAL" with: only CLOSED refuses on status (ERR_FEE_ASSESSMENT_CLOSED); PAID passes the state gate and is refused by the balance rule as ERR_PAYMENT_EXCEEDS_BALANCE — routes/reports.py:306-311
- §3.9 (sweep cascades) — insert — same guide-lapse PROBATION pinning, spelled out: not a term of the §3.8 derivation, written only from COMPLIANT, and undone by the next re-derivation over the three terms — routes/ops.py:80-140, calc.py:568-583

No PRD edits for the three fixture/test-arithmetic items (fixtures.py pre-issuance snapshot, test_14 131,002, test_17 duplicate unique keys) — PRD §3.4, §3.7 and §3.1 already determine those uniquely.

Pre-edit search log:

Edit A — (a) Subject: which fields a UseArea representation carries, specifically allocatable_service_days. (b) Grepped serialize.use_area -> only three callsites (setup.py:72 create/201, :79 read, :92 list), all through one serializer; read USE_AREA_FIELDS, calc.area_ledger/recompute_area (writes all six), setup.py:50-71 (seeds allocatable_service_days at insert, then recompute_area(bump=False)), and the allocation-summary endpoint (setup.py:95-110, six-field payload). (c) Widened the sentence to name demand_ratio/allocation_posture as well and to cover the list and 201 responses, because all three callsites share one serializer — wording limited to "the same six fields" so it makes no claim about version or the summary endpoint's differing shape.

Edit B — (a) Subject: date-pair ordering on use-area creation. (b) Grepped every as_date/req_date comparison across routes/ — bond expiration <= effective, certificate expiration <= effective, report period_end <= period_start, successor_end <= successor_start are all strict; only setup.py:44 is non-strict. Also checked every consumer of the stored season dates (reports.py:62-64 season window, guides.py:143 covers_season, ops.py) and confirmed store.as_date compares calendar-date parts only. (c) Scoped the wording to the season window alone and phrased it as "ordered only in the weak sense", so §2.5 tier 5's generic "every date pair correctly ordered" still governs the strict pairs elsewhere; added "calendar day" to match as_date's date-part comparison.

Edit C — (a) Subject: assessment-status gating of a payment and the reach of ERR_FEE_ASSESSMENT_CLOSED. (b) Read all four assessment mutators: record_payment (reports.py:292-324), finalize_assessment (:270, status != PROVISIONAL -> same error), close_assessment (:333), amend_report (:201); plus accept_report (:173-175), which recomputes an existing assessment without reverting its status — so PAID with a positive balance is reachable and must remain payable. Also calc.permit_fee_delinquent (PROVISIONAL/FINAL only) and calc.close_settled_assessments. (c) Deliberately scoped the new sentence to payments ("the only status that turns a payment away on its own") so it does not narrow ERR_FEE_ASSESSMENT_CLOSED at finalize/close/amend, and phrased the PAID clause as "passes that gate and is judged on the money instead" so the accept-into-a-paid-season path (positive balance, PAID) is still payable rather than excluded.

Edits D1/D2 — (a) Subject: provenance and persistence of a compliance_status value written outside the §3.8 derivation. (b) Grepped every derive_compliance caller and every direct compliance_status assignment: calc.py:581-595 (the one rule, three terms via compliance_value), callers in assurance.py:75,133, reports.py:31,288,323, enforcement.py:33, permits.py:148, ops.py:88; direct writes only at ops.py:139 (sweep step five) and the two creation dicts permits.py:218 / applications.py:301. Read guides.py:201-219 (manual authorization revoke) and confirmed it recomputes capacity but writes no PROBATION, so the cascade is sweep-only and both §3.1 and §3.9 describe the same single site. Verified sweep step ordering (step four re-derives before step five writes), so the value stands for the remainder of that run. (c) Widened from "does not persist" to also state the COMPLIANT-only precondition (ops.py:137) and that PROBATION/NONCOMPLIANT permits keep their standing; conditioned the undo on "the following write or sweep that re-derives compliance" rather than any write, since many endpoints (e.g. guide authorization) mutate a permit without re-deriving. Left §3.8's "never set by a request" untouched to avoid a new mismatch, adding the §3.9 cross-reference in §3.1 instead.

## Step 9: Complete PRD (three sequential file-partitioned subagent passes) — 2026-09-04T06:42:00.000Z

Orchestrator decision (recorded per the autonomy instruction): Step 9 was run as three SEQUENTIAL passes over disjoint partitions of implementation/, rather than one subagent scanning all 4,103 lines. Rationale — a single-agent full scan of a 74-endpoint / 648-line-calc implementation reliably runs out of working context and returns a PRD_COMPLETED.md that is byte-identical to its input (i.e. the scan silently never ran). Partitioning bounds each pass's reading load. Passes had to be sequential, not concurrent, because all three edit the same file in place. Partition: pass 1 = app/store/errors/envelope/security/shapes/routes{__init__,common,setup,applications,prospectuses}; pass 2 = routes{permits,plans,guides,assurance} + serialize; pass 3 = routes{reports,enforcement,ops} + calc.

Orchestrator verification: PRD.md 119,093 B -> PRD_FINALIZED.md 120,730 B -> PRD_COMPLETED.md 140,443 B, all 484 lines; PRD_COMPLETED.md is NOT byte-identical to its input (+19,713 B over PRD_FINALIZED.md, +17.9%), so all three passes really ran; tail still ends at the completed §5 error table. implementation/ has no .py modified after the 05:46Z green sweep (verified with `find -newermt`), so the recorded 8x109/109 result still describes the shipped code. __pycache__ dirs removed; no stray task_2646 server processes remain (a pid seen during the scan had already exited; killed/confirmed gone by exact pid, no broad pkill).

### Pass 1 (app/store/errors/envelope/security/shapes/routes{common,setup,applications,prospectuses}) — verbatim

PRD_FINALIZED.md: 484 lines / 120,730 bytes; PRD_COMPLETED.md: 484 lines / 129,174 bytes (24 lines revised in place, no lines added/removed, file still ends at the completed §5 error-code table). Cross-check: impl errors.py STATUS map matches the §5 catalogue exactly on all 64 ids; the only extras are the two transport fallbacks, now documented.

Counts: 22 ambiguity-pins, 3 mismatch-revisions.

- §2.2 — revise — ambiguity — api_request_id is `req_` + exactly 20 mixed-case alnum chars — envelope.py:19
- §2.2 — revise — ambiguity — api_request_timestamp comes from wall-clock time, not the logical clock (record timestamps do) — envelope.py:23
- §2.3 — revise — ambiguity — non-integer limit/offset is ERR_INVALID_REQUEST; empty string means absent — envelope.py:58-72
- §2.3 — insert — ambiguity — every listing filter is exact-match, unknown value matches nothing, only year filters must parse as int — routes/common.py:10-29
- §2.3 — insert — ambiguity — created_at ties break by insertion order following the listing's sort direction; id never a sort key — store.py:187-199, setup.py:92
- §2.4 — insert — ambiguity — server-minted timestamps read the logical clock; client-supplied dates are stored/echoed verbatim, bare YYYY-MM-DD accepted, comparisons on UTC calendar day — store.py:45-52,101-105, shapes.py:140-157
- §2.4 — insert — ambiguity — one request advances a record's version by at most 1 regardless of how many hops touch it — store.py:134-150
- §2.5 — insert — ambiguity — JSON null = absent; scalar coercion rules (digit strings, integral floats, "true"/"false"); bool never accepted as number; required strings non-blank; absent/unparseable body = {}, non-object body = 400 — shapes.py:12-137
- §2.7 — insert — ambiguity — allocation-summary data is the six figures plus use_area_id, no id/created_at/version, and writes nothing back — setup.py:95-110
- §2.8 — insert — ambiguity — client-supplied service-day counts capped at 3650; year fields bounded 1900-9999 — setup.py:29-30,167-172, applications.py:86-87, prospectuses.py:52
- §3.1 — revise — ambiguity — area_code collision is ERR_INVALID_REQUEST — setup.py:46-48
- §3.1 — revise — ambiguity — party_size_max/max_clients_per_guide at least 1; min_liability_coverage_cents at least 0 — setup.py:33-38
- §3.1 — revise — ambiguity — determined_capacity_service_days >= 0 and over-allocatable is ERR_INVALID_REQUEST; allocated_service_days required, >= 0 — setup.py:169-180
- §3.1 — insert — ambiguity — any number of DRAFT assessments may coexist per area/year — setup.py:182-197
- §3.1 — revise — ambiguity — contact_email non-empty, no syntax check — setup.py:120
- §3.1 — revise — ambiguity — verified is a required boolean; prequalification re-derives nothing else; answers 200 with the outfitter — setup.py:150-158
- §3.2 — revise — ambiguity — suspended-holder submission is ERR_INVALID_APPLICATION_STATE, judged after the DRAFT check — applications.py:154-157
- §3.2 — insert — ambiguity — hold_expires_at is never read back: an expired hold blocks nothing and is not swept — applications.py:205, ops.py (no reader)
- §3.2 — revise — MISMATCH — denial also re-derives the governing assessment (PRD had granted that only to withdrawal); denial from SUBMITTED recomputes nothing; withdrawal also re-derives prospectus_required — applications.py:241-248,261-267
- §3.2 — revise — ambiguity — denial_reason_code is a free-form non-empty string — applications.py:236
- §3.2 — revise — MISMATCH — application listing also filters on application_type and routing_decision (§3.2 had omitted both, §4 already had them) — applications.py:139-140
- §3.3 — revise — ambiguity — min_qualifying_score bounded 0-100, stored at 2 dp — prospectuses.py:54-60
- §3.3 — insert — ambiguity — issuing a solicitation does not check assessment/area agreement, offered days vs. allocation, or prospectus_required — prospectuses.py:34-89
- §3.3 — revise — MISMATCH — cross-area response is ERR_INVALID_REQUEST but is judged after both status checks, not at tier 5 — prospectuses.py:133-136
- §3.3 — insert — ambiguity — response endpoint answers with the application; close/award/cancel answer with the solicitation — prospectuses.py:152,169,218,239
- §3.3 — revise — ambiguity — expected_use_area_version is a required non-negative integer judged before the solicitation's status — prospectuses.py:177-184
- §3.3 — insert — ambiguity — area recomputed once per award; governing assessment re-derived once per distinct denied season_year; responsive_application_count not recounted to 0 — prospectuses.py:211-217
- §3.3 — revise — ambiguity — cancellation_reason_code is a required free-form non-empty string — prospectuses.py:226
- §3.4 — revise — ambiguity — solicitation/award mismatch is ERR_INVALID_APPLICATION_STATE, checked right after the application status — applications.py:340-349
- §3.4 — insert — ambiguity — new permit's open_noncompliance_points/authorized_client_capacity_total/service_days_used_ytd 0, fee_delinquent false, latest_performance_rating null — applications.py:294-317
- §5 — insert — ambiguity — off-catalogue transport responses: ERR_NOT_FOUND 404 for undefined paths, ERR_INVALID_REQUEST 400 for wrong method, ERR_INTERNAL 500; trailing slashes ignored — app.py:36-53,19

Deliberately left under-determined (no safe universal wording): sibling re-route in screen does not re-derive the siblings' own governing assessments (their pending totals are unchanged, so the omission is unobservable).

### Pass 2 (routes{permits,plans,guides,assurance} + serialize) — verbatim

Before: 484 lines, 129,174 chars. After: 484 lines, 134,925 chars (+5,751). Verified intact: still 484 lines, still ends at the completed §5 error-code table (| ERR_DEDUCTIONS_EXCEED_CAP | 422 |). All edits were surgical Edit calls; pass 1's edits preserved (confirmed by folded diff against PRD_FINALIZED.md before starting, so wording dovetails with pass 1's).

25 behaviors pinned across 23 Edit calls — 18 ambiguity-pins, 7 mismatch-revisions.

- §3.4 — revise — MISMATCH — activation recomputes all four derived signals (not just insurance/bond), judges bond_current against the permit's current required assurance, does NOT re-derive compliance_status, and recomputes both active_permit_count and prior_permit_count — routes/permits.py:96-99
- §3.4 — insert — ambiguity — indemnification takes no body, has no status precondition (terminal statuses included), and re-acknowledging is accepted with 200 + another version bump — routes/permits.py:48-55
- §3.5 — revise — MISMATCH — all four section keys must be present and each must be a JSON object; omitted/null is ERR_INVALID_REQUEST, {} is admissible — routes/plans.py:26-34,48
- §3.5 — insert — ambiguity — section_body required and must be an object; replacement recomputes completeness_score but leaves deficiency_sections as the last review left it — routes/plans.py:100-117
- §3.5 — insert — ambiguity — submit checks run plan-state -> permit-operability -> completeness (score recomputed immediately before judging), inverting the narrated order — routes/plans.py:127-136
- §3.5 — revise — ambiguity — deficiency_sections required, must be an array of declared section names; empty array accepted — routes/plans.py:163-170
- §3.5 — insert — ambiguity — rejection_reason_code is a required free-form non-empty string — routes/plans.py:205
- §3.5 — revise — ambiguity — plan read echoes the four section objects exactly as stored, plus rejection_reason_code and both reviewer ids — serialize.py:116-130
- §3.1 — insert — MISMATCH — qualify judges the two credential-safety conditions before the status precondition (inverting §2.5 tiers); an already-QUALIFIED guide with a good card is ERR_INVALID_REQUEST — routes/guides.py:97-109
- §4 — revise — MISMATCH — dropped the nonexistent qualification_level filter from the guide-roster row; only status is recognised — routes/guides.py:58-68
- §3.6 — revise — ambiguity — coverage_amount_cents >= 0; expiration strictly after effective on pain of ERR_INVALID_REQUEST — routes/assurance.py:35,41-42
- §3.6 — revise — MISMATCH — certificate filing recomputes all four signals (fee_delinquent and open_noncompliance_points re-read from their own rows) and re-derives compliance_status with §3.8's suspension propagation — routes/assurance.py:73-75
- §3.6 — insert — ambiguity — bond_amount_cents >= 0; end strictly after start — routes/assurance.py:102,106-107
- §3.6 — revise — MISMATCH — bond filing recomputes all four signals and re-derives compliance_status exactly as a certificate filing does — routes/assurance.py:131-133
- §3.6 — revise — MISMATCH — credential horizon tests the season_close_date of the permit's own use area (not "the area for the permit's current season year") — routes/guides.py:140-147
- §3.6 — insert — ambiguity — authorization revocation_reason_code is a required free-form string, conventionally HOLDER_REQUEST here — routes/guides.py:209
- §3.6 — insert — ambiguity — no permit-status precondition on authorization revoke, so a standing row is revocable against a suspended or terminal permit — routes/guides.py:201-219
- §3.8 — revise — ambiguity — suspend is from ACTIVE only (ERR_PERMIT_NOT_OPERATIONAL otherwise); suspension_reason_code free-form; suspended_until_date stored verbatim and never read back by any operation (grep-verified) — routes/permits.py:103-113
- §3.8 — insert — ambiguity — suspension leaves compliance_status and the four signals untouched, yielding the pair SUSPENDED/COMPLIANT — routes/permits.py:112, calc.py:622-633
- §3.8 — insert — ambiguity — reinstatement's points test recomputes the rolling window at that instant rather than reading the stored field — routes/permits.py:129
- §3.8 — revise — ambiguity — revoke from a terminal status is ERR_PERMIT_NOT_OPERATIONAL; revocation_reason_code free-form; pinned the governing-assessment selector (the single PUBLISHED assessment for the area whose assessment_year equals the permit's issuing season_year, nothing recomputed when none exists) as shared by every close-out path — routes/permits.py:159-162, calc.py:636-649,189-193
- §3.9 — insert — ambiguity — successor copies fee_schedule_code; every derived figure listed at its opening value; successor_term_end_date echoed verbatim while the computed term_start_date is server-minted (ISO 8601 UTC, three fractional digits, predecessor's time-of-day + 1 day); response is 201 carrying the successor — routes/permits.py:203-236
- §3.1 — insert — ambiguity — seasons_experience defaults to 0, minimum 0; hiring runs no credential test (NONE type or expired card accepted) — routes/guides.py:29-55
- §3.1 — insert — ambiguity — refiling promotes LAPSED only; PENDING_QUALIFICATION stays put and QUALIFIED keeps its status; no status precondition guards the filing — routes/guides.py:91-92
- §2.8 — insert — ambiguity — every rounded decimal and exact integer (cents included) travels as a bare JSON number, never a quoted string; a zero-fraction rounded figure reads 100.0 not 100, trailing zeros not preserved (0.8000 -> 0.8) — serialize.py:6-16, calc.py:98-102

No-new-mismatch verification performed: grepped every recompute_permit_signals / derive_compliance call site across assurance/enforcement/ops/reports/permits before asserting "all four signals" — claim holds system-wide, and the allow_suspend=True propagation wording was scoped to filings only (reinstatement passes allow_suspend=False). Traced close_out_permit -> recompute_governing_assessment(area, season_year_of_permit) and confirmed the sweep's expiry, the enforcement REVOCATION cascade and the succession close all share that selector. Enumerated all 15 serializer field-list constants against their store.insert() payloads: no field is withheld anywhere, so a planned blanket "and nothing else" claim was dropped. Re-checked every §4 table row for these endpoints against the decorators and qstr/qint sets — all correct except the qualification_level phantom, now fixed.

Deliberate non-changes: §3.9 succession contiguity already matches the impl comparison exactly; §4 acknowledge-indemnification "irreversible once set" is true (no path ever clears it), so only the missing idempotency/precondition facts were added.

### Pass 3 (routes{reports,enforcement,ops} + calc) — verbatim

Before: 484 lines / 134,925 bytes. After: 484 lines / 140,443 bytes (+5,518; no lines added or removed — every edit an in-paragraph replace, no new sections, no new paragraphs). 17 changes: 9 ambiguity-pins, 8 mismatch-revisions.

- §2.4 — revise — ambiguity — to_iso8601 is a required string parsed as ISO date/date-time (bare YYYY-MM-DD = midnight UTC, unparseable = ERR_INVALID_REQUEST), and data is exactly the resulting current_utc rendered in server ISO 8601 UTC with three fractional digits rather than echoed as submitted — ops.py:18-26 / store.py:45-52
- §3.6 — revise — MISMATCH — continuity is judged over the ACTIVE GENERAL_LIABILITY certificate set; other coverage_types are invisible to both tests — calc.py:240-291
- §3.6 — insert — ambiguity — insurance_current is true only when some single ACTIVE GL certificate is endorsed and alone reaches min_liability_coverage_cents (no summing), so a permit that passed the summed activation gate can still read false and drop to PROBATION — calc.py:262-269
- §3.7 — insert — ambiguity — filing ranges (service_days_used 1..3650, client_count >=1, gross_revenue_cents >=0, allowable_deductions_cents default 0 and >=0), period_end_date strictly after period_start_date (same-day = ERR_INVALID_REQUEST), and the permit must be ISSUED/ACTIVE else ERR_PERMIT_NOT_OPERATIONAL at tier 7 — reports.py:42-52
- §3.7 — revise — MISMATCH — the season test reads the area's single seasonal window whatever its own season_year; that season_year is never compared against the report's — reports.py:60-64
- §3.7 — revise — MISMATCH — acceptance republishes service_days_used_ytd as a fresh sum over every ACCEPTED report in every season (not an increment), recomputes all four derived signals with §3.8 suspension propagation, and an assessment the acceptance created opens at version 1 — calc.py:363-369 / reports.py:27-31,154-177
- §3.7 — insert — ambiguity — both bracket ceilings belong to the lower bracket (exactly 2,500,000 -> 300bp; exactly 10,000,000 -> 400bp) — calc.py:295-300
- §3.7 — insert — ambiguity — the provisional walk restamps applied_rate_bp/fee_component_cents on every accepted report of the season, not only the named one, without refreshing siblings' updated_at/version — calc.py:328-338
- §3.7 — revise — ambiguity — a FINAL, PAID or already-CLOSED assessment is refused at finalization with ERR_FEE_ASSESSMENT_CLOSED, judged before the pending-report test — reports.py:270-278
- §3.7 — revise — MISMATCH — finalization re-derives all four signals; the aggregate variant reads reports without writing, so each report keeps its provisional applied_rate_bp/fee_component_cents, and service_days_used_ytd is untouched — reports.py:279-288 / calc.py:322-334
- §3.7 — revise — MISMATCH — a payment re-derives all four derived signals and compliance_status, not fee_delinquent alone — reports.py:320-323
- §3.7 — revise — MISMATCH — an amendment re-reads all four signals, recomputes service_days_used_ytd as a fresh sum over every ACCEPTED report in every season, and judges ERR_FEE_ASSESSMENT_CLOSED immediately after the report's status check and ahead of the deduction cap — reports.py:198-207,236
- §3.8 — revise — MISMATCH — evaluation step four reads the permit's stored open_noncompliance_points (not recomputed over the rolling window at that instant), with the 30.0 cap applied before rounding — enforcement.py:59-61 / calc.py:448-460
- §3.8 — insert — ambiguity — recording an evaluation touches nothing else on the permit: the four signals and compliance_status stand, and no suspension can follow — enforcement.py:80-82
- §3.8 — insert — ambiguity — a REVOCATION action stamps revocation_reason_code NONCOMPLIANCE_ACTION and runs the revocation endpoint's full close-out, after which points and compliance are recomputed on the now-REVOKED row — enforcement.py:136-139 / calc.py:636-649
- §3.9 — insert — ambiguity — the sweep's INSURANCE_LAPSE suspension stamps suspended_until_date at the current logical instant + 30 days x (1 + UPHELD MAJOR count), server-minted with three fractional digits, and the point-threshold cascade takes precedence so both never fire on one permit in one run — ops.py:86-99 / calc.py:502-503
- §3.9 — insert — MISMATCH — steps four and six are unconditional, so every operable permit and every touched outfitter has updated_at/version advanced even on a no-op sweep, while certificate/bond/guide/authorization rows advance only when their own status moves — ops.py:80-85,142-144 / calc.py:527

Live verification (server on port 17263, killed by pid — no broad pkill): two endorsed 60,000,000 GL certs against a 100,000,000 minimum -> insurance_current false / PROBATION, confirming single-certificate semantics; a no-op sweep with all six counters zero still advanced permit version 3->4 and outfitter 2->3; set_current_utc with bare 2026-09-05 returned 2026-09-05T00:00:00.000Z; out-of-order acceptance restamped the earlier report from 300bp/600,000 to 400bp/800,000 while its version stayed 2; finalize produced FINAL_AGGREGATE 1,375,000 against the provisional sum 1,100,000 with reports keeping their provisional stamps.

Integrity: file still ends at the completed §5 error-code table with | ERR_DEDUCTIONS_EXCEED_CAP | 422 | as the final row; the five ## section headers (§2 line 11, §3 line 157, §4 line 333, §5 line 414) all in place. A line-level diff against PRD_FINALIZED.md shows 57 changed blocks, all replace (zero inserts/deletes) — the ~40 pass-1/pass-2 blocks all still present alongside pass 3's 17.

## Pipeline complete — 2026-09-04T06:42:00.000Z

workspace/PRD_COMPLETED.md written. Final artifact inventory: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9 files), test_suite/ (conftest + 22 test files, 109 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, sweep.log, implementation/ (22 files + results.1..8.json, all 109/109)}.
