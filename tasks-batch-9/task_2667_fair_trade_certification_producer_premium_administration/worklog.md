# Worklog — task_2667_fair_trade_certification_producer_premium_administration

## Step 1: Create task directory — 2026-09-04T04:06:03.106504167Z

Created tasks/task_2667_fair_trade_certification_producer_premium_administration/ and its workspace/ subdirectory. Index fixed by scenario number (2667) per orchestration instructions; no auto-allocation performed.

## Step 2: Scaffold generation — 2026-09-04T06:02:00Z

Wrote the three scaffold artifacts from the scenario text plus the scaffold-generator SKILL.md
spec only (no sibling task inspected):
- SCAFFOLD.yaml — 2797 lines; 12 entities, 9 state machines, 2 concurrency rules, 9 calculations,
  34 validations, 57 endpoints, 41 errors, 6 roles; api_prefix /fairtrade.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — 1759 lines; 9 rule blocks, 20 instances.
- SCAFFOLD_CORNER_DESIGN.yaml — 3490 lines; 9 sections, 78 instances (57 with test recipes,
  21 excluded_because stubs pointing at §1.8).

scaffold_lint.py: VERDICT clean lint (847 calls scanned). All 41 §1.6 error ids are referenced by
at least one §1.8/§1.9 instance; instance names are unique across both design files.

## Step 2 (orchestrator record — subagent summary verbatim) — 2026-09-04T06:03:00.000Z

All three scaffold artifacts for task 2667 are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2667_fair_trade_certification_producer_premium_administration/`)
- `SCAFFOLD.yaml` — 2797 lines, 144 KB. Top-level keys only: `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, global_constants, endpoints, errors, roles`. Neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present (verified programmatically).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1759 lines, 114 KB. Single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3490 lines, 224 KB. Single top-level key `scaffold_corner_design`.

**SCAFFOLD.yaml counts**: 12 entities, 9 state machines, 2 concurrency rules (`proposal-create-stale-fund`, `transaction-create-stale-seller-node`), 9 calculations, 34 validations (priority 1-34), 57 endpoints, 41 errors, 6 roles. `api_prefix: /fairtrade`; profile `expert_plus`, topology `graph`, state-machine shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`, layers = dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers, derived_field_reconciliation.

**§1.8 counts**: 9 rule blocks (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`), 20 instances.

**§1.9 counts**: 9 sections, 78 instances — 57 with full `test_recipe`, 21 `excluded_because` stubs deferring to a named §1.8 instance. Per section: entities 11, state_machines 10, calculations 8, validations 24, endpoints 8, errors 1, rbac 9, cross_cutting_complexity_layers 6, consistency_model 1.

**Verification**
- `scaffold_lint.py` verdict: clean lint — §1.5 endpoints 57, §1.1 entities 12, §1.8 instances 20, §1.9 instances 57, calls scanned 847; all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
- All 41 declared error ids referenced by at least one §1.8/§1.9 instance (zero uncovered).
- Instance `name` values unique across both design files (98 names, no duplicates).
- Every stub's `difficulty_instance` resolves to a real `rule_id / instance_name` pair; five stubs initially cited invented rule_ids and were corrected to `compensating_invariant`, `transitive_cascade`, `non_linear_state_machine`, `dual_variant_calc`.
- Every numeric assertion precomputed with `Decimal`/`ROUND_HALF_UP` (license fee 760725 at 600000 kg, 382950 at 100000 kg; premium 999920 at 12499 kg vs 1000000 at activation boundary; MAJOR deadline 2026-09-15, MINOR 2026-10-30; compliance score 100->85->80->95; `next_audit_due_at` 2028-08-08T00:00:00Z).
- No sibling task directory was read, listed, or grepped.

## Step 3: Copy shared files — 2026-09-04T06:03:30.000Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md -> workspace/INSTRUCTION.md (53 lines).

## Step 4: PRD generation — 2026-09-04T06:20:00.000Z

PRD generated and fully verified.

**Output:** workspace/PRD.md — 529 lines, 119,515 bytes. Written in 11 chunked appends (10 heredocs + one `cat` of the fixed §2.2 file); no truncation. File ends cleanly at the last row of the §5 error table (`ERR_LICENSE_FEE_UNPAID | 402 Payment Required`).

Orchestrator truncation check (independent): `tail -c 1200` confirms the file ends at a complete error-table row — a real section boundary, not mid-sentence. 29 markdown headings present. No regeneration needed.

**Section list (27 headings):** §1 Introduction; §2 Global Specifications — 2.1 RBAC, 2.2 API Response Structure (byte-identical verbatim), 2.3 Pagination, 2.4 Deterministic Logical Clock, 2.5 Common Resource Properties, 2.6 Precision/Rounding/Units, 2.7 Cascade Discipline Across the Certification Hierarchy, 2.8 Resolution Order and Referential Integrity, 2.9 Optimistic Concurrency on Parent Snapshots, 2.10 Validation Precedence, 2.11 Premium Fund Conservation, 2.12 Certified Volume and the Mass-Balance Credit Invariant; §3 Business Logic & Workflows — 3.1 Registering Holders and Mapping the Certified Chain, 3.2 Granting/Suspending/Withdrawing Certification, 3.3 Recording a Certified Trade: Minimum Floor and Premium, 3.4 Verification and Settlement, 3.5 Premium Fund Governance, 3.6 Audits/Graded Findings/Corrective Action, 3.7 The Compliance Sweep, 3.8 Label Licensing and On-Pack Mark Usage, 3.9 Volume Reporting and Counterparty Reconciliation; §4 Endpoint Definitions; §5 Error Code Catalogue.

**Coverage counts — mechanically verified against SCAFFOLD.yaml, 0 missing:** endpoints 57/57; error codes 41/41; validations 34/34 (numbered in priority order in §2.10); calculations 9/9 (incl. both PHYSICAL_TRACEABILITY/MASS_BALANCE premium variants and both SELLER_BASIS/BUYER_BASIS variance variants); state machines 9/9 with all 50 distinct from->to pairs verbatim; entity field names 124/124; request-body + query-param + computed output names 58 + 28 + 15 all present; enum values 87/87; roles 6/6; concurrency rules 2/2 (expected_fund_version->412 ERR_STALE_FUND_VERSION; expected_seller_node_version->412 ERR_STALE_NODE_VERSION); global constants 6/6.

**Hard Contract reports:** (1) Field-Name Coverage PASS — 0 missing tokens. (2) Rule Coverage PASS — all 50 transition pairs verbatim (9 added by targeted edits: SupplyChainNode ->RETIRED x3, PremiumCommittee ->DISSOLVED x3, Nonconformity ->OVERDUE x3, each with sibling-branch symmetry). (3) §3 Path Purity PASS — 1,107 backticked tokens in §3; zero `/`-leading tokens, zero bare HTTP methods, zero method+path combos, zero tables.

**Hard constraints honored:** SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml never read, grepped, or referenced; no sibling task directory accessed; the "harder than expert level" difficulty line was NOT forwarded to the doc generator.

**Scaffold inconsistencies adjudicated during writing** (endpoint `side_effects` treated as authoritative where sources conflicted): proposal `turnout_pct`/`approval_pct` are `0.00` at creation (null after a revise); VolumeReport created with `counterparty_volume_kg` 0 and `variance_pct` 0.00; the sweep's step-2 escalation comparison is inclusive (`>=`); step-3 suspension gated on `grade IN {CRITICAL, MAJOR}`; `ERR_PREMIUM_USE_BLOCKED_BY_SUSPENSION` blocks creation for SUSPENDED/TRANSITIONING/DECERTIFIED but blocks disbursement only for SUSPENDED; `ERR_LICENSE_FEE_UNPAID` is decide-time only.

## Unit test generation (test_helpers/ + test_suite/)

- 9 helper modules (2915 lines) and 17 test modules + conftest (3856 lines) at the task root.
- 110 tests, each tagged with exactly one `Design:` line as the last docstring line.
- Queue A (SCAFFOLD_DIFFICULTY_DESIGN): 20 of 20 non-stub instances translated.
- Queue B (SCAFFOLD_CORNER_DESIGN): 55 of 57 non-stub instances translated; 2 skipped as
  PRD-unreachable (`rbac/chair_who_voted_in_the_round_cannot_close_it`,
  `validations/escalated_finding_blocks_a_new_trade_even_after_reinstatement`).
- Verified: no bogus/stub-pointing tags, every generated .py compiles, 110 tests collected.

## Step 5: Unit test generation — 2026-09-04T07:15:00.000Z

Test generation is complete. Everything is at the task root; nothing was written into `workspace/` (orchestrator verified: no test_helpers/ or test_suite/ under workspace/).

## Files written

`test_helpers/` (2,915 lines): `__init__.py` 145, `api_client.py` 434, `api_errors.py` 110, `assertions.py` 587, `constants.py` 242, `factories.py` 704, `fixtures.py` 322, `test_users.py` 105, `types.py` 266.

`test_suite/` (3,872 lines): `conftest.py` 16, `test_01_trade_pricing_and_premium_variants.py` 255, `test_02_reconciliation_basis_and_finding_deadlines.py` 191, `test_03_proposal_and_cap_review_loops.py` 195, `test_04_cascade_chains.py` 195, `test_05_error_precedence_pairs.py` 133, `test_06_boundary_and_precision.py` 192, `test_07_cross_entity_state_dependencies.py` 192, `test_08_audit_window_contention.py` 172, `test_09_fund_capacity_and_conservation.py` 292, `test_10_resource_shapes_and_reads.py` 319, `test_11_lifecycle_transitions.py` 235, `test_12_computed_figures.py` 267, `test_13_endpoint_behaviours.py` 219, `test_14_role_and_ownership_boundaries.py` 250, `test_15_stale_snapshots_and_running_aggregates.py` 268, `test_16_governance_refusals.py` 244, `test_17_chain_audit_and_report_refusals.py` 437.

## Coverage

**110 tests**, each carrying exactly one `Design:` tag as the final docstring line (verified by AST walk).

- **Queue A (SCAFFOLD_DIFFICULTY_DESIGN, §1.8): 20 / 20 non-stub instances translated, 0 skipped.**
- **Queue B (SCAFFOLD_CORNER_DESIGN, §1.9): 55 / 57 non-stub instances translated, 2 skipped.** Per section: entities 11/11, state_machines 7/7, calculations 4/4, validations 15/16, endpoints 5/5, errors 1/1, rbac 7/8, cross_cutting_complexity_layers 4/4, consistency_model 1/1.

Skipped instances (PRD-first filter, gaps left as gaps — no xfail, no placeholder):
- `Corner/rbac/chair_who_voted_in_the_round_cannot_close_it` — §4 restricts ballot casting to `CommitteeMember` and §2.1 segregation forbids a chair voting on its own committee's proposal, so a chair can never appear among a round's voters; the recipe's setup state is unreachable and the asserted 403-on-close cannot be produced.
- `Corner/validations/escalated_finding_blocks_a_new_trade_even_after_reinstatement` — §3.2 permits reinstatement only when `open_critical_count` is 0 and no finding sits at `ESCALATED`, so the recipe's "sweep escalated the finding, officer then reinstated" setup is unreachable.

Three individual assertion clauses were dropped where the PRD does not uniquely derive them (instance cores kept): the `success == false` envelope field (the error `data` carries only `error_id` and `message`), the `role_in_report` stored field/enum (it exists only as a list filter parameter), and the zero-length reporting period asserted as `ERR_REPORT_PERIOD_OVERLAP` (ordering of `period_end` vs `period_start` is ambiguous between the priority-3 shape check and priority 27). Two recipes also needed coherent clock movement or a node-bearing holder to be executable at all (late-CAP submission needs the clock past the deadline; certify requires >=1 `REGISTERED` node).

## Verification

`python3 -m py_compile` clean on all 26 generated `.py` files; `pytest --collect-only` collects 110 tests with no import or collection errors; programmatic tag diff against both design yamls shows 0 bogus tags, 0 tags pointing at stub instances, 0 missing queue-A instances and exactly the 2 intentional queue-B skips; unused-import sweep clean. `__pycache__`/`.pytest_cache` artifacts removed.

## Step 6: Implementation generation — 2026-09-04T07:15:30.000Z

Implementation complete and smoke-verified.

## Files written (`workspace/implementation/`)

| file | lines | contents |
|---|---|---|
| `start.sh` | 10 | guarded launcher (`if ! python3 -c "import flask"` ... `exec python3 app.py`), executable |
| `requirements.txt` | 1 | `Flask>=2.2` |
| `app.py` | 62 | registers 9 blueprints under `/fairtrade`, `ApiError`/`HTTPException`/generic handlers, `0.0.0.0:$PORT` (default 10000) |
| `common.py` | 218 | every enum + constant, `Decimal` helpers (`rhu`/`money`/`vol`/`pct`/`floor_int`), logical clock (`clock_now`, `set_clock`, default `2026-08-01T00:00:00Z`), ISO with 3 fractional digits |
| `errors.py` | 58 | `ApiError` with HTTP status for all 41 error ids |
| `response.py` | 62 | `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more`, `error_id`/`message` |
| `store.py` | 159 | 12 in-memory dicts, `stamp_new`/`stamp_event`/`touch_once` (one version bump per row per request), `*_or_404` for all 10 404 families |
| `auth.py` | 31 | `X-User-ID` / `X-User-Role`, `ERR_UNAUTHENTICATED` -> `ERR_UNAUTHORIZED` |
| `validators.py` | 220 | shape layer (priority 3), pagination 1..100/default 10 |
| `calc.py` | 189 | all 9 calculations incl. pinned mass-balance lot rounding and tiered licence fee |
| `domain.py` | 373 | cascades: suspension (4 hops), decertification, ledger writes + fund compartments, committee threshold transitions, mass-balance credit, chain traversal, 6-step compliance sweep |
| `routes_holders.py` | 259 | lifecycle + licence + payments + traceability summary |
| `routes_nodes.py` | 129 | node registration, harvest declarations, lists |
| `routes_committees.py` | 117 | committees, funds, ledger entries |
| `routes_transactions.py` | 261 | record/verify/settle/void with full precedence cascade |
| `routes_reports.py` | 171 | filing, overlap exclusion, both reconciliation bases |
| `routes_proposals.py` | 368 | draft/open-vote/ballot/close-vote/revise/disburse/cancel + tally, window capacity, SoD |
| `routes_audits.py` | 291 | scheduling with travel buffer + holder exclusivity, findings (5 pinned steps), CAP loop, closure |
| `routes_marks.py` | 111 | filing + decision (licence -> traceability -> fee order) |
| `routes_system.py` | 31 | compliance sweep, clock set (auth-exempt only when both headers are absent) |

Total 3121 lines. All files `python3 -m py_compile` clean; `__pycache__` removed. No persistence, no file I/O, no seeding anywhere (verified by grep and by two cold boots).

## Endpoint coverage

**57/57 exact match.** Registered Flask url_map diffed programmatically against the PRD §4 table: `missing from impl: []`, `extra in impl: []` (only Flask's own `/static` beyond the 57).

## Smoke test result

Launched on `PORT=18667`, killed afterwards by resolved listening PID (`ss -ltnp`) — never a pattern kill. Two scripted phases, each against a genuinely fresh process:

- **Phase 1 (45 calls, 0 failures)** — happy path end to end: clock set, holder registration -> node mapping -> certification (node activation), harvest declaration, priced trade (`settled_unit_price_cents_per_kg` 440, `gross_value_cents` 5 280 000, physical premium 1 200 000), verify -> settle -> ACCRUAL entry, committee `FORMING -> ACTIVE` at the 1 000 000 threshold, proposal -> ballots -> close-vote (turnout 80.00 / approval 100.00 -> APPROVED) -> disburse, audit schedule -> start (window-not-open 409 first) -> MAJOR finding (deadline `2026-09-20T09:00:00.000Z`, grace 14, score-at-raise 100) -> CAP submit -> cap-review SoD 403 for the raiser then ACCEPT -> audit close -> `next_audit_due_at 2028-08-09`, licence pricing + payment, `FT_CERTIFIED_100` mark request approved against `chain_mode ALL_PHYSICAL`, volume report reconciled (12000.0 / 0.0 / MATCHED), sweep, plus envelope/error checks (401 missing headers, 401 illegal role, 422 shape, 404 holder, 422 `limit=0`).
- **Phase 2 (26 calls, 0 failures)** — deterministic time and cascades: mass-balance premium 58 350, `ERR_STALE_NODE_VERSION` 412, auditor travel-buffer conflict 409, CRITICAL finding drops the score to 60 with a 10-day deadline, sweep 1 -> `overdue_count 1`, CAP after deadline 409, sweep 2 -> `escalated_count 1 / suspended_holder 1 / suspended_node 1 / disputed_transaction 1` with the reservation released (`reserved_output_kg` back to 0), reinstate blocked by the escalated finding, sell-down window, client `decertify` correctly refused from `TRANSITIONING`, and sweep 3 past `transition_deadline_at` -> `decertified_holder_count 1`.

Two bugs found and fixed during verification: `req_number(..., exclusive_min=True)` in `routes_marks.py` (the helper takes a *bound*, not a flag, so it was rejecting volumes <= 1) and a `timedelta`-vs-missing-constant slip in the auditor travel-buffer comparison in `routes_audits.py`.

Notable PRD-fidelity calls: `ERR_COMMITTEE_NOT_ACTIVE` enforced only on vote opening (§2.10 priority 14) so mid-vote restriction cannot brick a round; no SoD block on ballot casting, otherwise the vote-closing SoD rule (priority 9) would be unreachable; no auditor binding on raising a finding (priority 7 lists audit *start* only); mark-decision order licence -> traceability -> fee per §2.10 rather than the §3.9 sentence order; CAP submission against `OVERDUE`/`ESCALATED` returns `ERR_CAP_DEADLINE_PASSED` while `CAP_SUBMITTED`/`CLOSED` returns `ERR_INVALID_STATE_TRANSITION`.

## Step 7: Test/fix iteration — 2026-09-04

Two 8-round parallel stability sweeps (`--isolation per-test-server`, 110 tests/round, launched
under `setsid nohup` and joined with `wait`).

**Iteration 1 — 104/110 in all 8 rounds.** Six failures, identical in every round (no flakiness):
five assertion/field-name mis-translations in `test_suite/` and one test setup that violated a
higher-precedence PRD rule. No implementation defect found; no test deleted.

| test | diagnosis | fix |
|---|---|---|
| `test_03 ::test_a_short_first_round_sends_the_proposal_back_and_round_two_approves_it` | §3.5 increments `current_round` on the revision branch *and* again on opening a round, so the second close sits at 3, not 2 | assertion corrected to 3 |
| `test_03 ::test_round_two_is_tallied_from_round_two_ballots_only` | same double increment: the reopened round's ballots carry `round_number` 3 | `rounds.count(2)` -> `rounds.count(3)` |
| `test_06 ::test_the_gram_past_the_cap_moves_the_tier_and_costs_exactly_one_cent` | `KeyError: 'total'` — `expected_license_fee()` returns `license_fee_cents` | key corrected |
| `test_08 ::test_the_buffer_guards_the_days_before_a_booking_as_well` | candidate window 2026-07-25..07-29 is backdated against the 2026-08-01 clock, so §2.10 priority 23 `ERR_INVALID_AUDIT_WINDOW` correctly pre-empts priority 24 | new `_two_producers_with_a_later_booked_auditor` books 2026-09-01..09-05 and the candidate becomes 2026-08-25..08-29, still forward of the clock and exactly on the inclusive buffer edge |
| `test_09 ::test_voided_trade_is_reversed_without_losing_its_verification_history` | `KeyError: 'premium_amount_cents'` — the PRD field is `premium_cents` | field name corrected |
| `test_12 ::test_a_fractional_tonnage_rounds_the_premium_and_the_contract_total_half_up` | `volume_kg` sent as the JSON string `"1234.567"`; §2.10 priority 3 requires the declared JSON type, so the 422 was correct | call site now passes the number `1234.567` |

**Iteration 2 — 110/110 in all 8 rounds.** `workspace/implementation/` untouched throughout.

## Step 7: Test-and-fix iteration loop — 2026-09-04T07:55:00.000Z

All 8 rounds pass at 110/110. Final report:

## Summary

**Iterations run:** 2 (each an 8-round parallel `per-test-server` sweep, 110 tests/round, launched under `setsid nohup` and joined with `wait`).

**Tests deleted:** none. Every failure survived STEP 1 (PRD verbatim-covers the rule and uniquely derives the outcome); all six were mis-translations in `test_suite/`, so STEP 2 applied.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header helper was at fault.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful on all six failures.

**Fixes applied to `test_suite/`:**

- `test_03_proposal_and_cap_review_loops.py`, `TestProposalVoteForksBackToRevision::test_a_short_first_round_sends_the_proposal_back_and_round_two_approves_it` — asserted `current_round == 2`. PRD §3.5 states both "*The revision branch* ... `current_round` increments by 1" and "**Opening a round.** ... incrementing `current_round` by 1", unconditionally, so open->close-as-revision->revise->open lands on 3. Assertion corrected to 3.
- same file, `::test_round_two_is_tallied_from_round_two_ballots_only` — same double increment means the reopened round's ballots carry `round_number` 3 (round 2 is never balloted). `rounds.count(2) == 3` -> `rounds.count(3) == 3`.
- `test_06_boundary_and_precision.py`, `TestLicenseTierBreakpoint::test_the_gram_past_the_cap_moves_the_tier_and_costs_exactly_one_cent` — `KeyError: 'total'`; `expected_license_fee()` in `test_helpers/assertions.py` returns the key `license_fee_cents`. Key corrected (values 382950 / 382951 were already right).
- `test_08_audit_window_contention.py`, `TestAuditorTravelBuffer::test_the_buffer_guards_the_days_before_a_booking_as_well` — the candidate window `2026-07-25..2026-07-29` is backdated against the default clock `2026-08-01`, so §3.6/§2.10 priority 23 `ERR_INVALID_AUDIT_WINDOW` correctly pre-empted the priority-24 buffer check. Added `_two_producers_with_a_later_booked_auditor` (existing booking `2026-09-01..2026-09-05`) and moved the candidate to `2026-08-25..2026-08-29` — still forward of the clock, and exactly on the inclusive `existing window_start - 3 days` buffer edge the test is meant to probe. The exact-`error_id` assertion was kept.
- `test_09_fund_capacity_and_conservation.py`, `TestVoidingASettledTrade::test_voided_trade_is_reversed_without_losing_its_verification_history` — `KeyError: 'premium_amount_cents'`; the PRD field is `premium_cents` (§3.3 "frozen at recording time"). Field name corrected.
- `test_12_computed_figures.py`, `TestPremiumRounding::test_a_fractional_tonnage_rounds_the_premium_and_the_contract_total_half_up` — sent `volume_kg` as the JSON string `"1234.567"`; §2.10 priority 3 requires "correct JSON type per the field's declared type", so the 422 was correct behaviour. Call site now passes the number `1234.567`. (Only call site in the suite sending a numeric body field as a string; the factory pass-through was left intact so negative type tests stay possible.)

**Final sweep evidence** (`workspace/implementation/results.$i.json`): round 1 110/110, 2 110/110, 3 110/110, 4 110/110, 5 110/110, 6 110/110, 7 110/110, 8 110/110.

Notes: iteration 1's six failures were identical in all 8 rounds — no flaky/load-induced failures appeared in either sweep, and no reaping signature (`Terminated`) was present. `__pycache__` and `.pytest_cache` cleaned; no stray `test_*` dirs under `workspace/`.

**Orchestrator independent verification:** re-read all 8 `results.$i.json` directly — each reports `passed 110 / failed 0 / total 110 / errors 0`; `grep -c 'def test_'` across `test_suite/` totals 110, matching. Step 8 is NOT skipped: Step 7 ran 2 iterations with 6 `test_suite/` fixes, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) does not hold.

## Step 8: PRD finalization — 2026-09-04T08:15:00.000Z

Done. `PRD_FINALIZED.md` is a one-line patch of `PRD.md`.

## Counts
- PRD.md: 529 lines / 119,515 bytes; PRD_FINALIZED.md: 529 lines / 120,008 bytes — line delta 0.0%, byte delta +0.41%. Tail verified identical (both end at the last row of the §5 error-code table at `ERR_LICENSE_FEE_UNPAID`).

## Changes
- §3.5 "Tallying and the three-way fork" / *the revision branch* (line 319) — **insert** — added one consequence clause: the revision branch's `current_round` increment is not consumed by the reopening, so send-back -> revise -> reopen lands two above the round just closed, the skipped number is never balloted, and revision itself leaves `current_round` alone — `implementation/routes_proposals.py:235` (revision-branch increment), `:123` (open-vote increment), `:258` (revise leaves `current_round` untouched), `:137` (ballots only while `UNDER_VOTE`).

## Per-edit pre-edit search log
Edit 1 — §3.5 revision branch
- (a) Subject: `current_round` / `round_number` lifecycle across the propose->vote->revise->revote loop.
- (b) Enumerated and read: `routes_proposals.py` `draft` (`:90`, opens at 0), `open_vote` (`:123`, `+1`, only entry into `UNDER_VOTE`, requires `DRAFT`), `cast_ballot` (`:137` status gate, `:143` duplicate check on `current_round`, `:153` stamps `round_number = current_round`), `_counted_ballots`/`_restamp_tally` (`:31-42`, tally filters `round_number == current_round`), `close_vote` all three branches (`:203-235`; only the revision branch touches `current_round`), `revise_proposal` (`:239-265`, mutates title/category/amount and nulls the two tallies, never `current_round`), plus a whole-tree grep for `current_round`/`round_number` (no other writer anywhere in `implementation/`). Also grepped PRD for every `current_round`/`round_number` mention (lines 126, 305, 307, 309, 311, 319) to confirm no §4 endpoint text contradicts the added clause.
- (c) Adjustment: wrote the addition purely as a derived consequence of the two increment rules already in the PRD rather than as a new rule, and scoped "no ballot ever carries the skipped number" to the impl's actual guarantee (`UNDER_VOTE`-only ballot casting) instead of stating it as a bare universal. Also added "revision itself leaves `current_round` alone" so the sentence cannot be read as licensing a decrement or reset on `revise`.

## Items requiring no PRD change (verified against impl)
- Both round-number test corrections trace to the same clause above; the impl (double increment) already matched PRD verbatim, so only the misleading-rationale wording was pinned, no rule changed.
- `license_fee_cents` (PRD §3.8 names the field; `routes_holders.py:239`, `calc.py:85`) and `premium_cents` (PRD §3.3; `calc.py:52`, `routes_transactions.py:178`) — response-field names already in PRD; pure `test_suite` key bugs.
- Audit window backdating: PRD §3.6 "window_start must not fall earlier than the clock's current date" plus §2.10 priority 23 before 24 — exactly `routes_audits.py:35-49`; the fix was a fixture-date bug.
- `volume_kg` sent as a JSON string: PRD §2.10 priority 3 already determines the 422 — `validators.py:104-110` rejects non-numbers; call-site bug only.

**Orchestrator independent verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (319), and `tail` confirms PRD_FINALIZED.md still ends at the same real section boundary.

## Step 9: PRD completeness scan — 2026-09-04T09:05:00.000Z

Run as THREE sequential file-partitioned passes over `implementation/` (a single-pass scan of a 20-file / 3121-line implementation against a 120KB PRD risks a no-op that leaves PRD_COMPLETED.md byte-identical to its source). Each pass edited `workspace/PRD_COMPLETED.md` in place with targeted Edit calls; pass A created it from PRD_FINALIZED.md.

### Pass A — core modules (app.py, common.py, errors.py, response.py, store.py, auth.py, validators.py, calc.py, start.sh, requirements.txt)

Source PRD_FINALIZED.md 529 lines / 120,008 chars -> 531 lines / 125,525 chars (+2 lines, +5,517 chars, 13 changed lines). **11 ambiguity-pins, 2 mismatch-revisions.**

- §2.1 — revise — ambiguity — header rejection covers whitespace-only values; role match exact/case-sensitive on the raw header — auth.py:17-22
- §2.2 — revise — ambiguity — `api_request_id` = `req_` + exactly 20 uppercase hex chars — common.py:217
- §2.3 — revise — ambiguity — `limit`/`offset` must be plain base-ten integer strings — validators.py:167-175
- §2.3 — revise — ambiguity — list ordering tie-break = server insertion counter; underscore-prefixed internals never serialized — store.py:75-77, common.py:212-214, response.py:16
- §2.3 — revise — ambiguity — enum-domain filters validated (`ERR_INVALID_REQUEST`); identifier/free-text filters matched literally, unknown value -> empty page — validators.py:194-207
- §2.4 — revise — ambiguity — accepted `to_iso8601` forms; clock may move backwards; sub-ms precision truncated not rounded — common.py:146-163,172-173
- §2.6 — insert — ambiguity — incoming numerics rounded to declared precision BEFORE range checks; wire form numbers-not-strings, money integer, volumes/percentages decimals — validators.py:113-131, response.py:9-19
- §2.7 — revise — **mismatch** — cascade version bumps at most once per row per request — store.py:52-72
- §2.9 — revise — ambiguity — server handles requests one at a time, never interleaved — app.py:61
- §2.10 item 3 — revise — ambiguity — absent/empty/`null` body read as `{}`; strict type checks; string trimming/limits; enum arrays >=1 member keeping duplicates — validators.py:15-90,154-163
- §2.11 — revise — ambiguity — "the fund of a holder" = holder's earliest-created fund — store.py:127-130
- §4 preamble — revise — ambiguity — paths match with or without trailing slash — app.py:27
- §5 preamble — revise — **mismatch** — table no longer claimed exhaustive; four transport-level ids pinned (`ERR_NOT_FOUND` 404 unknown path, `ERR_INVALID_REQUEST` 405 bad method, `ERR_INVALID_REQUEST` 400 malformed, `ERR_INTERNAL` 500) — app.py:41-57

Clean results: `errors.py` HTTP_STATUS matches all 41 rows of §5 exactly; `calc.py` matches every formula, constant, threshold and rounding order with no gaps.

### Pass B — domain + core routes (domain.py, routes_holders.py, routes_nodes.py, routes_committees.py, routes_transactions.py)

125,525 -> 133,149 chars (531 lines throughout; all in-paragraph). **24 ambiguity-pins, 6 mismatch-revisions (30 edits).**

- §2.1 — revise — mismatch — dropped false claim that `ERR_SEGREGATION_OF_DUTIES` covers verifying a trade you recorded — routes_transactions.py:102-142
- §3.1 — insert — ambiguity — `upstream_node_id` need not name a node of the same holder — routes_nodes.py:33,45
- §3.1 — insert — ambiguity — node under SUSPENDED/DECERTIFIED holder still created `REGISTERED` — routes_nodes.py:51
- §3.1 — revise — ambiguity — traceability summary is computed, no `id`/`version`; `brand_node_count` = eligible starting set; `total_available_credit_kg` sums all holder nodes — domain.py:264-299
- §3.1 — revise — ambiguity — harvest: `certified_volume_kg` >=0 (3dp), `harvest_season` non-empty <=80 stored nowhere, no harvest resource minted, 201 returns updated node, holder `version` also increments — routes_nodes.py:72-95
- §3.1 — insert — ambiguity — registration is the only occasion a fund is minted; one fund per producer org for life — routes_holders.py:49-79
- §3.2 — revise — ambiguity — certify with no `REGISTERED` node -> `ERR_INVALID_STATE_TRANSITION`; three open-grade counters recomputed alongside `compliance_score` — routes_holders.py:133-144
- §3.2 — insert — ambiguity — unclean reinstatement -> `ERR_INVALID_STATE_TRANSITION` — routes_holders.py:169-175
- §3.2 — revise — mismatch — mark-usage withdrawal on suspension not conditional on licence having been ACTIVE; `decided_by_user_id` stays null — domain.py:197-206
- §3.2 — revise — mismatch — decertify `reason` optional (<=1000) persisted nowhere; `suspension_reason`/`transition_deadline_at` untouched — routes_holders.py:213-219, domain.py:210-212
- §3.2 — revise — mismatch — decertification reduces `reserved_output_kg` only where the trade still held a reservation — domain.py:222-231
- §3.3 — insert — ambiguity — `product_code` not checked against certified scope; `contract_date` never compared to the clock — routes_transactions.py:31,35
- §3.3 — insert — ambiguity — seller node activity checked before buyer's — routes_transactions.py:52-55
- §3.4 — insert — ambiguity — re-verification credit requirement applies whatever the `traceability_mode`; shortfall -> `ERR_INVALID_STATE_TRANSITION` — routes_transactions.py:121-126
- §3.4 — insert — ambiguity — the four accepted status/`outcome` pairs are exhaustive — routes_transactions.py:137-139
- §3.4 — insert — ambiguity — `ACCRUAL` written only when seller holder has a fund and `premium_cents` > 0 — routes_transactions.py:177-182
- §3.4 — revise — ambiguity — `annual_certified_volume_kg` recompute covers every settled outbound trade when `license_year` is null and replaces the running figure outright — domain.py:64-79
- §3.4 — revise — mismatch — void `reason` optional <=1000 not persisted; fund-balance precondition only when a fund exists and `premium_cents` > 0 — routes_transactions.py:194-207,218
- §3.5 — insert — ambiguity — `chair_user_id` non-empty <=200 chars — routes_committees.py:23
- §3.5 — insert — ambiguity — `holder_type` test precedes uniqueness test; `certificate_status` never consulted when constituting — routes_committees.py:30-36
- §3.5 — insert — ambiguity — `fiscal_year` fund filter must be a plain base-ten integer string — routes_committees.py:80
- §3.5 — insert — ambiguity — RESTRICTED draft-cancellation cascade decrements both proposal counters, never below 0 — domain.py:124-132,161-169
- §3.6 — insert — ambiguity — `next_audit_due_at` rendered as midnight-UTC instant of the derived date — domain.py:51-61
- §3.7 — insert — ambiguity — semantics of all six sweep counters incl. step-six retirements/rejections counted nowhere — domain.py:306-313,361-369
- §3.7 — insert — ambiguity — step two walks OVERDUE findings ascending `deadline_at`/`created_at`, also step three's order — domain.py:328-338
- §3.7 — revise — mismatch — holder suspended only if currently CERTIFIED; `next_audit_due_at` re-derived once per sweep with exactly one `version` bump — domain.py:347-359
- §3.8 — insert — ambiguity — `license_year` integer >=1, `licensed_volume_kg` >=0 at 3dp — routes_holders.py:228-229
- §3.8 — revise — ambiguity — issuing re-derives `license_fee_settled` to false, consults no `certificate_status`, refused with `ERR_INVALID_STATE_TRANSITION` once TERMINATED — routes_holders.py:231-243
- §3.8 — insert — ambiguity — payment `amount_cents` integer >=0, accepted whatever `label_license_status` reads, no stored `license_year` — routes_holders.py:251-257
- §3.8 — insert — ambiguity — payment's 201 response carries the updated holder — routes_holders.py:259

Flagged to pass C: `domain.recompute_next_audit_due` breaks a `window_end` tie by the LATER `created_at` while §3.6 step five said the earlier — judged unobservable since only `window_end` is consumed.

### Pass C — governance routes (routes_proposals.py, routes_audits.py, routes_reports.py, routes_marks.py, routes_system.py) + cross-pass consistency read

133,149 -> 140,525 chars (531 lines; all in-paragraph). **14 ambiguity-pins, 15 mismatch-revisions (29 changes).**

- §2.1 — revise — mismatch — dropped false claim that SoD covers deciding a mark request you filed or voting on a proposal whose committee you chair; such a ballot is accepted, the chair is stopped only at close — routes_marks.py:53-87, routes_proposals.py:128-162
- §2.4 — insert — ambiguity — clock-endpoint exemption all-or-nothing; one header alone -> `ERR_UNAUTHENTICATED`, both with non-officer role -> `ERR_UNAUTHORIZED` — routes_system.py:22-27
- §2.10 item 5 — revise — mismatch — added `ERR_COMMITTEE_NOT_FOUND` for the draft's `committee_id` — routes_proposals.py:62
- §3.5 Drafting — insert — ambiguity — `use_period_end` strictly after `use_period_start` is a priority-3 shape check ahead of committee resolution — routes_proposals.py:59-60
- §3.5 Drafting — revise — mismatch — committee `status` not consulted at drafting — routes_proposals.py:47-79
- §3.5 — revise — mismatch — proposal creation increments both committee and fund `version` — routes_proposals.py:99, domain.py:124-132
- §3.5 Opening a round — revise — mismatch — `ERR_COMMITTEE_NOT_ACTIVE` arises only on open-vote — routes_proposals.py:118-120
- §3.5 Casting ballots — insert — ambiguity — `round_number` filter must be a plain base-ten integer string — routes_proposals.py:359, validators.py:210-214
- §3.5 approval branch — insert — ambiguity — the 80% ceiling is exact/unrounded, comparison inclusive — routes_proposals.py:181-182
- §3.5 rejection branch — revise — mismatch — committee `version` increments too — routes_proposals.py:232
- §3.5 Revision — insert — ambiguity — three mandatory inputs, window unamendable, no suspension/fund re-check, no counter moves — routes_proposals.py:240-265
- §3.5 Cancellation — insert — ambiguity — `reason` <=1000 chars validated, persisted nowhere — routes_proposals.py:303
- §3.5 Cancellation — revise — mismatch — committee `version` increments even when the counter is clamped at 0 — routes_proposals.py:324, domain.py:124-132
- §3.6 Scheduling — insert — ambiguity — `auditor_user_id` non-empty <=64 chars — routes_audits.py:28
- §3.6 Scheduling — insert — ambiguity — holder `certificate_status` and `audit_type` never cross-checked — routes_audits.py:33
- §3.6 Scheduling — revise — mismatch — scheduling runs step five and unconditionally bumps holder `version` — routes_audits.py:77-78
- §3.6 Running — insert — ambiguity — both further preconditions carry `ERR_INVALID_STATE_TRANSITION`; window checked before holder; only the audit row mutated — routes_audits.py:92-104
- §3.6 Raising a finding — insert — ambiguity — any `Auditor` may raise; `auditor_user_id` not compared — routes_audits.py:109-119
- §3.6 step five — revise — mismatch — `window_end` tie-break rewritten as deterministic-but-unobservable — domain.py:51-61
- §3.6 CAP submission — revise — mismatch — audit counters recomputed but cannot move; audit row and holder aggregates untouched; response 201 — routes_audits.py:205-211
- §3.6 steps four/five re-run list — revise — mismatch — the pair re-runs on CAP accept, audit close, and once per escalated-finding holder in the sweep; scheduling runs step five alone; OVERDUE-only transitions, CAP submit and CAP reject re-run neither — routes_audits.py:77,153-158,180-182,210,238-243, domain.py:356-359
- §3.7 closing line — revise — mismatch — a finding moved OVERDUE then ESCALATED in one sweep advances `version` by 2 — domain.py:319-338
- §3.8 Requesting mark usage — insert — ambiguity — only `label_license_status` consulted — routes_marks.py:28-34
- §3.8 Deciding — revise — mismatch — approval checks ordered license -> traceability (FT_CERTIFIED_100 only) -> fee per §2.10 — routes_marks.py:66-78
- §3.9 Filing — insert — ambiguity — period ordering is a priority-3 shape check ahead of holder resolution; no certificate-status/relationship checks; counterparty may be the filer — routes_reports.py:33-40
- §3.9 Filing/listing — insert — ambiguity — `role_in_report` token-matching semantics plus `ERR_INVALID_REQUEST` fallback — routes_reports.py:136-146
- §3.9 Reconciling — insert — ambiguity — reconcilable only while SUBMITTED; second attempt -> `ERR_INVALID_STATE_TRANSITION` — routes_reports.py:104-106
- §4 table — revise — mismatch — `GET /fairtrade/audits/{id}/nonconformities` description corrected to a list description — routes_audits.py:278-291
- §4 table — revise — mismatch — `GET /fairtrade/trade-transactions` description corrected to a list description (disclosed as outside partition; copy-paste wart fixed for coherence)

`recompute_next_audit_due` verdict: NOT observable, so not pinned to impl's later-`created_at` choice; the PRD's false "earlier `created_at`" claim was replaced with under-determined wording.

Cross-pass consistency read found and fixed three contradictions in A/B-edited sections: (1) §2.1 overclaimed SoD scope (impl has exactly two raise sites); (2) §3.6 "step four alone runs again ... every time a finding changes status" contradicted impl and pass B's own §3.7 edit; (3) §3.7 claimed every swept entity's `version` increments by exactly 1, contradicting the reachable OVERDUE->ESCALATED double increment and §2.7's pass-A wording. Deliberately left alone: §3.5's `FORMING -> ACTIVE` sentence (the `committee_on_balance_rise` branch is unreachable from disburse/cancel).

### Orchestrator final verification

- `workspace/PRD_COMPLETED.md`: 531 lines / 140,525 chars; NOT byte-identical to PRD_FINALIZED.md (118 changed lines across the three passes); 29 headings intact; tail ends at the `ERR_LICENSE_FEE_UNPAID` row of the §5 table — a real section boundary, no truncation.
- No `.py` file under `workspace/implementation/`, `test_suite/` or `test_helpers/` is newer than `results.1.json`, so Steps 8 and 9 touched documentation only and the green 8-round sweep (110/110 x 8) remains valid evidence for the shipped code.
- Final layout as specified: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}. No stray test dirs under workspace/.

**Pipeline complete through Step 9.**
