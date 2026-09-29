# Worklog — task_2750_new_home_structural_warranty_insurance

## Step 1: Create task directory — 2026-09-04T15:57:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2750_new_home_structural_warranty_insurance` and its `workspace/` subdirectory. Index 2750 was pre-assigned by the orchestrating invocation; no scan of `./tasks/` was performed and no index was auto-allocated (32 concurrent pipelines on this host would collide).

## Step 2: Generate scaffold — 2026-09-04T17:53:00.000Z

Subagent summary (verbatim):

Task 2750 scaffold is complete and lint-clean.

Files:
- SCAFFOLD.yaml — 2632 lines
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — 1864 lines
- SCAFFOLD_CORNER_DESIGN.yaml — 6301 lines

`SCAFFOLD.yaml` top-level keys are `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — it contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`. Each design index has exactly one top-level key. The scenario is stored verbatim minus the "harder than expert level" directive line (grep confirms no leak into any of the three files).

SCAFFOLD.yaml inventory:
- 11 entities: Builder, UnderwritingReview, Homeowner, Neutral, WarrantyPolicy, CoverageTerm, WarrantyTransfer, Claim, StructuralAssessment, ReserveEntry, EscalationCase (three are `common_fields: false` immutable rows)
- 8 state machines on 7 entities (WarrantyPolicy carries two parallel axes: coverage and premium); Claim has 15 statuses with 6 terminal states and a builder-obligation/insurer-backed fork that rejoins
- 2 concurrency rules: `transfer-request-stale-policy` (`expected_policy_version`), `reserve-entry-stale-claim` (`expected_claim_version`)
- 11 calculations: `builder_risk_score` and `claim_net_payable` are the two dual-variant ones; plus `policy_premium`, `coverage_term_schedule`, `claim_obligor_assignment`, `structural_designation`, `builder_loss_ratio`, `transfer_fee`, `escalation_deadline`, and the two conservation identities
- 39 validations (priorities 1-75), 55 endpoints under `api_prefix: /warranty` plus the `POST /_clock/set_current_utc` control endpoint, 54 errors, 5 roles (`role_model: segregation_of_duties`, two entity-backed identities)
- `complexity_profile`: graph topology, branching state machine, layers `cascading_side_effects`, `dual_variant_calculation`, `optimistic_concurrency`, `derived_field_reconciliation`, `consistency_model: immediate`

Design index counts:
- §1.8 — 18 instances, 2 per rule across all 9 rule ids: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`
- §1.9 — 83 instances (65 live recipes + 18 `excluded_because` stubs) across all nine guide sections: Table 1 Entities 12, Table 2 State Machines 12, Table 3 Calculations 12, Table 4 Validations 9, Table 5 Endpoints 4, Table 6 Errors 22, Table 7 RBAC 6, Cross-Cutting Complexity Layers 5, Consistency Model 1. All 54 error ids are triggerable from the two indexes; every stub cites an existing §1.8 instance by name (14 distinct citations) and carries no `test_recipe`; all 101 instance names are unique across §1.8 union §1.9.

Lint verdict (final run): clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5. Coverage: 55 endpoints, 11 entities, 18 §1.8 instances, 65 §1.9 instances, 1353 calls scanned.

Two defects were caught and fixed on the way to that verdict: a capture of `consumed_cents` on `CoverageTerm` (the declared field is `consumed_limit_cents`), and a `builder-response` payload using `ACCEPT` instead of the declared enum member `ACCEPT_OBLIGATION`. No sibling task directory was read at any point.

Orchestrator verification: all three files present with the line counts above; `grep -ri "expert level"` over the task dir returns nothing, so the difficulty directive did not leak; `workspace/` and `worklog.md` survived the subagent.

## Step 3: Copy shared files — 2026-09-04T17:53:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T18:08:00.000Z

Subagent summary (verbatim):

PRD generated at `workspace/PRD.md`. Line count: 457 lines.

Section inventory (26 headings):
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Actors, Identity Headers and RBAC; 2.2 API Response Structure (verbatim block, confirmed byte-identical to `section-2.2-response-structure.md`); 2.3 Pagination; 2.4 Resource Identity, Audit Fields and the Logical Clock; 2.5 Money, Rates and Rounding Discipline; 2.6 Nested Paths and Foreign-Key Discovery; 2.7 Optimistic Concurrency Control; 2.8 Validation Precedence; 2.9 Two Conserved Quantities and Cascade Discipline; 2.10 Posture Gating and Segregation of Duties
- §3 Business Logic & Workflows — 3.1 Opening a Builder File and Scoring It; 3.2 Loss Monitoring, Reassessment and Builder Failure; 3.3 Enrolling a Closed Home; 3.4 The Two Policy Axes; 3.5 Passing the Warranty to a Subsequent Buyer; 3.6 Filing, Investigating and Designating a Claim; 3.7 Obligation Routing: Two Arms, One Join; 3.8 The Reserve Ledger; 3.9 The Panel, Mediation and Binding Arbitration
- §4 Endpoint Definitions (4 columns, 55 rows)
- §5 Error Code Catalogue (2 columns, 54 rows)

Coverage confirmation (machine-verified against the scaffold):
- Entities 11/11; entity field names 104/104 present, 0 missing
- Endpoints 55/55 — every method+path pair present exactly once, 0 missing; request-body/output identifiers 69/69; query params 30/30
- State machines 8/8, all 41 state values and all 46 transitions expressed with from/to, preconditions paired to error IDs, and side effects (including the three-link builder-default cascade and the three-link limit-exhaustion cascade)
- Calculations 11/11 as precise prose with every constant embedded (no pseudocode, no fuzzy quantifiers)
- Validations 39/39 as the ordered §2.8 ladder with per-rung error IDs, status codes and exact endpoint sets
- Errors 54/54 with 0 HTTP-status mismatches
- Roles 5/5; enum values 89/89; OCC rules 2/2 each naming write endpoint, version field, error ID and 412

Tail verification: `tail -40`/`tail -6` show the file ending on the complete final table row `| ERR_AUTHORIZATION_BELOW_DISBURSED | 422 |` — a genuine section boundary at the end of §5, no mid-sentence cut, no truncated row, no audit footer. Built via one Write plus eight chunked `cat >> ... << 'PRDEOF'` appends, so the 64k single-Write truncation mode was avoided.

Hard Contracts:
- Contract 1 (Field-Name Coverage): PASS — 104/104 entity fields, 69/69 body/output identifiers, 30/30 query params, 0 missing.
- Contract 2 (Rule Coverage): PASS — all six high-risk categories plus tail walked; one gap found and fixed (claim's zero/null initial settlement fields added to §3.6).
- Contract 3 (§3 Path Purity): PASS — 937 backtick tokens scanned in §3; 0 `/`-prefixed, 0 bare HTTP methods, 0 method+path combos, 0 tables.

Neither design index was opened, grepped or referenced; no sibling task directory was read; the PRD text never mentions any scaffold or design file.

Orchestrator verification of the known truncation failure mode: `wc -l` = 457; `tail -25` confirms the file ends on the complete final row of the §5 error table (`ERR_AUTHORIZATION_BELOW_DISBURSED | 422 |`), a real section boundary, not mid-sentence — no regeneration needed. `grep -ni "scaffold|expert level|design index" PRD.md` returns nothing, so neither the scaffold nor the difficulty directive leaked into the contract the implementer reads.

## Step 6: Generate implementation — 2026-09-04T18:41:00.000Z

Subagent summary (verbatim):

The implementation is complete, compiling, and smoke-tested.

File inventory (`workspace/implementation/`):
- `start.sh` 9 — launcher; installs Flask only if missing, `exec python3 app.py`
- `requirements.txt` 1 — `flask>=2.0`
- `app.py` 101 — Flask app, Decimal-aware JSON provider, `ApiError`/404/405/500 envelope handlers, blueprint registration, `PORT` default 10000
- `db.py` 137 — in-memory dict tables, logical clock, id/audit stamping, one-version-bump-per-row-per-request bookkeeping
- `errors.py` 88 — 55-entry error catalogue (id -> HTTP status) + `ApiError`
- `response.py` 91 — `meta`/`response_type`/`data` envelope, `req_`+20 alnum ids, pagination validation and slicing
- `middleware.py` 63 — `X-User-ID`/`X-User-Role` auth, role admission, per-request serialisation lock
- `validators.py` 201 — rung-8 shape checks (strings/ints/bools/enums/rates/dates/instants/arrays)
- `calc.py` 281 — every pinned constant and formula (risk score/class, premium per-component, term specs, structural designation, dual-variant settlement waterfall, betterment, loss ratio, posture, transfer fee)
- `store.py` 331 — FK resolution, aggregates, reserve journal helpers, builder-default and limit-exhaustion cascades, epoch sweep, neutral window-conflict math
- `listing.py` 28 — list-filter helpers
- `routes/builders.py` 235 (12 endpoints), `routes/parties.py` 82 (6), `routes/policies.py` 231 (9), `routes/transfers.py` 171 (7), `routes/claims.py` 251 (10), `routes/ledger.py` 136 (5), `routes/escalations.py` 209 (5 escalation endpoints + the clock blueprint), `routes/__init__.py` 1

Total 2647 lines. `python3 -m py_compile` passes on all 17 modules (`__pycache__` removed afterwards).

Endpoint count: 55 / 55. A `url_map` dump prints exactly 55 method+rule pairs, path-for-path identical to the PRD §4 table: 54 under `/warranty` plus `POST /_clock/set_current_utc` registered on a separate un-prefixed blueprint.

Logical clock: `db.CLOCK_EPOCH = 2026-08-01T00:00:00Z` is set at import time, so every boot starts at the epoch. `POST /_clock/set_current_utc` (ComplianceOfficer only) validates `to_iso8601`, refuses any earlier instant with `ERR_CLOCK_REGRESSION` (422), then runs the epoch sweep in-request — terms `OPEN`->`ELAPSED` where `end_date < clock date` first, then policies `ACTIVE`->`EXPIRED` where the `BASE`/`STRUCTURAL` term has elapsed, bumping each touched row's version — and returns `{current_utc, expired_policy_count, elapsed_term_count}`. All domain dates/instants read this clock; only `created_at`/`updated_at`/`api_request_timestamp` use wall time.

Smoke test (port 51750, single PID, killed with `fuser -k 51750/tcp` only) — two scripted passes, both green:
1. Envelope/auth/pagination (401/403/404/422 shapes), builder DRAFT->SUBMITTED->UNDER_REVIEW->APPROVED (risk score 33.00, class B), homeowner registration, enrollment with 3 base terms (structural limit = full purchase price, deductible 250000), premium invoice->payment->activation (with `ERR_PREMIUM_NOT_PAID` before payment), transfer with `ERR_STALE_POLICY_VERSION` then approve+record, claim intake->investigation->assessment->routing (builder arm, net 3312000) -> refusal -> insurer arm -> approve -> reserve entry -> payment (`ERR_SEGREGATION_OF_DUTIES` for the adjudicating adjuster) -> `CLOSED_PAID`, clock advance with `elapsed_term_count: 2`, loss-monitor read.
2. Fresh boot: denial (release of 1978000, deadline +60d), `ERR_NEUTRAL_CREDENTIAL_MISMATCH`, mediation booking, `ERR_NEUTRAL_WINDOW_CONFLICT` from a second denied claim inside the 120-minute pad, `ERR_SESSION_WINDOW_NOT_STARTED`, impasse (deadline reset +30d), arbitration with `prior_case_id` and `binding: true`, award SoD 403 then award -> `CLOSED_AWARDED`, payment + reversal restoring `paid_cents` to 0 and the term to `limit == remaining`, `ERR_ENTRY_NOT_REVERSIBLE` on double reversal. Both conservation identities asserted after every money move.

Two apparent failures during scripting were spec-correct behaviour, not bugs: enrollment refused with `ERR_BUILDER_POSTURE_FROZEN` after the builder's loss ratio blew past 1.2000, and `ERR_INVALID_CLAIM_STATE` (rung 12) rather than `ERR_MEDIATION_NOT_EXHAUSTED` (rung 14) when arbitration is requested on a `DENIED` claim.

One design change made this session: `db.mark()` now applies the version bump immediately with a per-request identity guard (instead of deferring to `flush_touches()`), because handlers serialise the row before the request ends — responses would otherwise have shown a stale `version`/`updated_at`. Exactly-one-bump-per-row-per-request still holds.

No seeded data: `db.py` creates 11 empty dicts at import and nothing writes to them outside a request handler; there is no SQLite file, no JSON dump, no `/tmp` cache, no fixture loader. Verified empirically: after killing the loaded server and re-invoking `start.sh`, all seven list endpoints returned `data: []` with `total_count: 0`.

Orchestrator note: Steps 5 and 6 were launched as two background agents. They overlapped for the whole of Step 6's run, so the implementation generator was told — and confirms — it never read `test_suite/` or `test_helpers/`; the isolation the skill wants from same-message launch was preserved by prohibition plus the fact that no test file existed when the impl agent started.

## Step 5: Generate unit tests — 2026-09-04T19:28:00.000Z

Subagent summary (verbatim):

Test infrastructure and suite for task 2750 are complete and verified.

Inventory (all at the task root, nothing under `workspace/`):
`test_helpers/` — 9 files, 2513 lines: `__init__.py` 42, `types.py` 443, `constants.py` 97, `api_errors.py` 124 (all 54 error ids + HTTP map registered), `api_client.py` 337 (55 methods = 55 PRD endpoints), `test_users.py` 81, `assertions.py` 354, `factories.py` 309, `fixtures.py` 726.
`test_suite/` — 17 files, 9650 lines: `conftest.py` 50, then `test_01_builder_risk_scoring` 237/4 tests, `test_02_settlement_and_premium_math` 652/10, `test_03_state_machine_cycles_and_forks` 289/4, `test_04_cascades_and_cross_entity_dependencies` 496/8, `test_05_validation_precedence_pairs` 269/4, `test_06_scheduling_and_interval_semantics` 326/5, `test_07_conservation_and_payment_reversal` 409/4, `test_10_entity_shapes_and_reads` 819/12, `test_11_state_machine_axes` 850/10, `test_12_calculation_edges` 798/15, `test_13_validation_guards` 1203/20, `test_14_endpoint_behaviours` 458/4, `test_15_error_catalogue_lookup_and_state` 676/7, `test_16_error_catalogue_coverage_and_ledger` 692/13, `test_17_access_control` 907/23, `test_18_concurrency_and_consistency` 519/7.
150 test functions, 158 collected cases (one parametrised function in file 15 expands to 9).

Coverage against the two design indices:
- Queue A (§1.8): 39 tests over 18/18 difficulty instances, every instance >=2 tests.
- Queue B (§1.9): 111 tests over 65/65 non-stub corner instances, every instance >=1 test.
- Skipped instances: none. No `pytest.mark.skip` / `xfail` / placeholder anywhere. A handful of sub-asserts inside kept instances were dropped as not uniquely derivable (BASE-term intra-mint order, which the PRD orders only by `start_date`; `decision_reason`'s initial value; two reserve-journal `total_count` presumptions).
- All 18 `excluded_because:` stubs verified: every `difficulty_instance` pointer resolves to a real §1.8 name, and none of the 18 has a test or tag.

Audit results:
- Tag audit (AST-based): 83 distinct `Design:` tags, exactly one per test and always the last docstring line; every tag resolves to a real instance under the correct `rule_id`/`section`; zero untagged, dual-tagged, stub-pointing or unknown-namespace tags.
- AST parse check: OK across all 26 files.
- Collection: `pytest test_suite/ --collect-only -q` -> 158 tests collected, no import or collection errors. No test was run against a server.
- Path check: task root holds `test_helpers/`, `test_suite/`; `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`. Nothing under `workspace/implementation/` was read or written, and no sibling task directory was touched.
- Zero occurrences of the word "scaffold" outside the mandated tag lines. Money is integer cents throughout; timestamps go through the canonicalising helpers.

Design-input defects found (tests follow the PRD, not the yaml):
1. `DRYWALL_FINISH` and `FINISH_DEFECT` appear as `defect_category` values in several recipes; neither is a declared enum member — substituted `WORKMANSHIP_DEFECT`.
2. The builder-arm settlement literal `1662500` uses the 5% betterment tier; PRD §3.7 selects the 8% tier once the deductible is zeroed, giving 1610000. Two independent agents converged on that figure.
3. A corner recipe asserts a fresh claim is `REPORTED`; PRD §3.6 pins `SUBMITTED`.
4. A corner recipe asserts `remaining_limit_cents == 4482000` on the STRUCTURAL term using the systems cap; the PRD gives the uncapped 42982000.
5. A corner recipe leaves a claim `APPROVED` after the final draw; PRD §3.8 closes it to `CLOSED_PAID` when `paid_cents == net_payable_cents`.

Orchestrator verification: `find` confirms `test_helpers/` and `test_suite/` exist only at the task root — neither was written under `workspace/`, so no relocation was needed before Step 7.

## Step 7: Run tests and iterate — 2026-09-04T19:54:00.000Z

Subagent summary (verbatim):

Clean sweep reached. Summary:

Iterations run: 2 (each an 8-round concurrent sweep under `setsid nohup`).

Iteration 1 result: 153/158 in all 8 rounds — 5 deterministic failures (identical union across every round, no flakiness):
1. `test_06::test_session_starting_when_another_ends_still_conflicts_through_the_turnaround` — setup 409 `ERR_STRUCTURAL_ASSESSMENT_REQUIRED`
2. `test_06::test_session_two_hours_clear_of_the_turnaround_is_booked` — same setup 409
3. `test_10::test_enrollment_naming_an_unknown_builder_returns_builder_not_found` — `KeyError: 'response_type'`
4. `test_15::test_body_foreign_keys_that_do_not_resolve_return_not_found_for_the_named_entity` — got `ERR_ROLE_NOT_PERMITTED`, expected `ERR_RESERVE_ENTRY_NOT_FOUND`
5. `test_17::test_a_blank_identity_header_is_treated_exactly_as_an_absent_one` — `requests.exceptions.InvalidHeader` (client-side, request never sent)

All five were test bugs under STEP 2 (setup/request inconsistent with PRD); no assertion was weakened.

Tests deleted: none. Every failing test's rule was verbatim in PRD.md and uniquely derivable.

Fixes applied to `test_helpers/`: none — the bugs were all local to `test_suite/`.

Fixes applied to `test_suite/`:
- `test_06_scheduling_and_interval_semantics.py`, `_panel_world_with_one_booked_session()` — the second claim is filed as `STRUCTURAL_CRACKING`, and PRD §3.6 line 288 states adjudicating such a claim with no engineering assessment on file is refused with `ERR_STRUCTURAL_ASSESSMENT_REQUIRED`; the fixture now files one assessment (`file_structural_assessment`, added to the import list) before routing, so the DENY that the scheduling assertions depend on is reachable.
- `test_10_entity_shapes_and_reads.py`, `test_enrollment_naming_an_unknown_builder_returns_builder_not_found` — `validate_error` returns the envelope's `data`; the test read `response_type` and `error.message` off it. Per PRD §2.2 `response_type` lives on the envelope and `error_id`/`message` directly inside `data`, so it now asserts `response.json()["response_type"] == "error"` and `error_data["message"].strip()`.
- `test_15_error_catalogue_lookup_and_state.py`, `test_body_foreign_keys_that_do_not_resolve_return_not_found_for_the_named_entity` — the payment-reversal probe acted as `ClaimsAdjuster`, but PRD §3.10 line 310 / §4 line 385 make reversal `ComplianceOfficer`-exclusive, so rung 2 (role) correctly pre-empted rung 7 (body FK). Fixture switched to `compliance_officer_headers`. Implementation precedence was correct and was left alone.
- `test_17_access_control.py`, `test_a_blank_identity_header_is_treated_exactly_as_an_absent_one` — whitespace-only header values are rejected by `requests`/HTTP before the wire, so that variant is untransmittable. Switched to empty-string values, which the same PRD §2.1 sentence covers verbatim ("absent, empty, or consists only of whitespace"); the assertion (`ERR_UNAUTHENTICATED`, 401) is unchanged. Implementation `middleware.authenticate` already handles both empty and whitespace.

Fixes applied to `implementation/`: none. No implementation defect was found; all 158 assertions trace to PRD prose the implementation already honours.

Final sweep per-round figures (from `workspace/implementation/results.1..8.json`, all written 19:47):
round 1: 158/158, round 2: 158/158, round 3: 158/158, round 4: 158/158, round 5: 158/158, round 6: 158/158, round 7: 158/158, round 8: 158/158.

`worklog.md` was not touched. One note for hygiene: my ad-hoc single-test spot checks on port 39751 left one stale server bound at one point, which produced a spurious `ERR_CLOCK_REGRESSION`; I killed that PID explicitly and the port is free.

Orchestrator verification of the sweep artifacts (independent re-read, not taken on trust): all eight `results.$i.json` exist, each reports `passed=158 total=158 failed=0 errors=0 skipped=0` with per-round durations 306–309s and mtimes clustered within 3 seconds of one another (epoch 1788551225–1788551228), consistent with one concurrent 8-round sweep. `grep Terminated workspace/sweep.log` finds nothing, so the setsid wrapper held and no round was reaped.

Step 8 decision: NOT skipped. The skip condition requires zero deletions AND zero `test_suite/` fixes AND zero `test_helpers/` fixes AND zero `implementation/` fixes; Step 7 applied 4 `test_suite/` fixes, so the sites it touched are candidate PRD-silence spots and Step 8 must inspect them. Because there were 0 `implementation/` fixes, a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 outcome here — the implementation never changed, so PRD.md may already pin every behaviour at those four sites.

## Step 8: Finalize PRD — 2026-09-04T20:02:30.000Z

Subagent summary (verbatim):

`PRD_FINALIZED.md` is written. Result: one single-sentence edit; the other three Step 7 items were pure fixture bugs at sites PRD already pins verbatim.

Line counts:
- `PRD.md`: 457 lines / 99,233 bytes
- `PRD_FINALIZED.md`: 457 lines / 99,444 bytes
- Delta: 0 lines (0.00%), +211 bytes (one line revised in place)

Changes:
- §3.6 (engineering assessments, line 258) — revise — appended: "Filing carries no from-state precondition of its own: an assessment may be put on file against a claim in any `status` — before the claim has been routed, while it awaits adjudication, or after it has closed." — `implementation/routes/claims.py:114-137`

Per-edit pre-edit search log:

Edit 1 — §3.6 assessment filing has no from-state guard
- (a) Subject: the preconditions and effects of `POST /warranty/claims/{id}/structural-assessments`, specifically whether the claim's `status` gates the filing. Traces to Step 7 item 1/2: the `test_06` fixture repair inserts `file_structural_assessment(...)` while the claim is in `UNDER_INVESTIGATION` (before `route_claim`), a state PRD never authorises or forbids for this operation.
- (b) Impl paths enumerated: `routes/claims.py:114-137` `file_assessment` (the sole creator — confirmed by `grep "assessments\["` across `implementation/`, one hit at `claims.py:133`): resolves the claim via `store.get_claim` (rung 6 only), validates body, stamps `assessed_by_user_id`/`assessment_date`, raises `claim["designated_structural"]` on a true verdict, `db.mark(claim)` — zero `status` inspection; `store.assessments_of_claim` (`store.py:107`) and its two consumers, `routes/claims.py:208-211` (the `ERR_STRUCTURAL_ASSESSMENT_REQUIRED` guard, existence-only, verdict-agnostic, both `APPROVE` and `DENY`, correctly ordered after rung-13 `ERR_COVERAGE_LIMIT_EXHAUSTED`) and `claims.py:249` (list); `calc.structural_designation`; `db.mark`/`db.touch` (version bump is status-agnostic); `validators.req_string_array`/`req_rate`/`req_bool`. Also confirmed no other endpoint re-runs the settlement waterfall on a flag flip (`store.apply_waterfall` callers: routing, `join_insurer_arm`, default cascade only), so the new sentence does not imply a recompute anywhere.
- (c) Wording adjustment: dropped a planned second clause ("...and filing one never re-runs the settlement waterfall") as out of scope and already implied by §3.7's pinned waterfall trigger list; kept the claim scoped to `status` alone (not to term status, role, or path resolution) so it stays true of the single impl path and does not narrow `ERR_CLAIM_NOT_FOUND` or the `ClaimsAdjuster`-only admission already stated in the same paragraph.

Items deliberately left unpatched (PRD already uniquely determines impl):
- Item 1/2 — `ERR_STRUCTURAL_ASSESSMENT_REQUIRED`: PRD §3.7 line 288 pins the guard verbatim (both branches, existence-only, the two `defect_category` values); `claims.py:208` matches, and rung 13-before-14 ordering matches §2.8. Also re-verified the now-unblocked turnaround assertions: `store.neutral_window_conflict` widens only the requested window by 120 min and compares half-open (`lo < other_end and other_start < hi`), exactly §3.9's wording; the status filter is moot because `BOOKED_STATES` equals the full case-status vocabulary.
- Item 3 — response envelope: `response.py:46-52` puts `response_type` on the envelope and `error_id`/`message` inside `data`, verbatim §2.2. Enrollment's rung 3 -> rung 7 order (`policies.py:44-53`) matches §2.8.
- Item 4 — reversal role precedence: `ledger.py:87` is `@endpoint(ROLE_COMPLIANCE)`; §2.1 line 21 and the §4 table make reversal ComplianceOfficer-exclusive, and §2.8 puts rung 2 ahead of rung 7. Impl was correct.
- Item 5 — blank identity headers: `middleware.py:38` rejects `None`, empty and whitespace-only for both headers before role admission, verbatim §2.1.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (the §3.6 assessment-filing sentence), both files 457 lines — consistent with the reported +211-byte in-place revision.

## Step 9: Complete PRD — 2026-09-04T20:26:00.000Z

Run as three sequential passes partitioned by implementation module over one shared `PRD_COMPLETED.md`; pass 1 owned the `cp` from `PRD_FINALIZED.md`, passes 2 and 3 edited in place with the Edit tool only. Partition: pass 1 = app.py, db.py, errors.py, response.py, middleware.py, validators.py, listing.py, routes/builders.py, routes/parties.py; pass 2 = calc.py, store.py, routes/policies.py, routes/transfers.py; pass 3 = routes/claims.py, routes/ledger.py, routes/escalations.py.

### Pass 1 summary (verbatim)

Diff stats: `PRD_FINALIZED.md` 457 lines / 99,444 chars -> `PRD_COMPLETED.md` 457 lines / 105,846 chars — +6,402 chars, 24 diff hunks, zero new paragraphs or sections. Counts: 22 ambiguity-pins, 3 mismatch-revisions.

Changes:
- §2.1 — insert — ambiguity — neither header is trimmed/normalised beyond the blank test; role must match character-for-character and `X-User-ID` is carried verbatim into ownership comparisons and actor stamps — `middleware.py:38-45`
- §2.1 — revise — MISMATCH — "Every carrier-side role may read every resource under `/warranty`" was false: builder list, review journal and loss monitor exclude `ClaimsAdjuster`, and the neutral list excludes `UnderwritingOfficer`; now defers to the §4 table and names the four exceptions — `routes/builders.py:201,211,222`, `routes/parties.py:76`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — `response.py:21`
- §2.2 — insert — ambiguity — `api_request_timestamp` is an envelope stamp read from the host wall clock, not the logical clock — `response.py:27`, `db.py:70`
- §2.3 — insert — ambiguity — integerhood of `limit`/`offset` judged on raw query text (optional `+`/`-` then digits); empty value or decimal point fails — `response.py:55-65`
- §2.3 — insert — ambiguity — `created_at` ties are broken by server insertion order, so descending pages are the exact reverse — `db.py:100-101`
- §2.3 — revise — ambiguity — `has_more` pinned as `offset + len(page) < total_count`, so an out-of-range offset gives empty data with `has_more` false — `response.py:41`
- §2.4 — insert — MISMATCH — §2.4 claimed time is "a logical clock, never the host's wall clock"; `created_at`/`updated_at` are in fact wall-clock stamps that advance without operator action and are never compared to domain dates — `db.py:70-74`
- §2.4 — insert — ambiguity — a freshly created row's `updated_at` equals its `created_at` — `db.py:80-81`
- §2.4 — insert — ambiguity — boot is a clean slate: every collection empty, no seeded entity data — `db.py:19-36`
- §2.5 — insert — ambiguity — rates/ratios/scores are JSON numbers both ways; a string is `ERR_INVALID_REQUEST`; `0.0000` serialises as `0.0` — `validators.py:119-131`, `app.py:26-34`
- §2.5 — insert — ambiguity — date format is strict `\d{4}-\d{2}-\d{2}` naming a real day; body instants accept `Z` or a numeric offset and a zone-less value is read as UTC; emitted instants always `Z` + 3 fractional digits — `validators.py:143-176`, `db.py:61-67`
- §2.6 — insert — ambiguity — filters match by exact string equality; an undeclared enum value or unresolvable id is neither 422 nor 404 but an empty page; `designated_structural` accepts `true/false/1/0` case-insensitively — `listing.py:10-28`
- §2.8 rung 8 — insert — ambiguity — absent/unparseable/non-object body behaves as `{}`; explicit JSON `null` is treated as absent — `validators.py:16-35`
- §3.1 — insert — ambiguity — `attestation_signed` is a required boolean but either value submits the file, it is not persisted, and the builder row is the response — `routes/builders.py:62-68`
- §3.1 — insert — ambiguity — `intake_note` is any string incl. blank, unbounded length, validated but never persisted — `routes/builders.py:76`
- §3.1 — insert — ambiguity — the review row echoes `decision` and `reviewer_notes` (null when omitted) and is itself the 201 response body, not the builder — `routes/builders.py:104-117`
- §3.2 — insert — ambiguity — loss-monitor `data` holds exactly the six keys, no `id`/audit/pagination, and the read echoes the four stored figures without recomputing — `routes/builders.py:221-235`
- §3.2 — insert — ambiguity — reassessment requires `underwriting_status` exactly `APPROVED`, else `ERR_INVALID_BUILDER_STATE` — `routes/builders.py:129-130`
- §3.2 — insert — ambiguity — `reason` on suspension/reinstatement/default is required, non-blank, unbounded and discarded; builder file is the response — `routes/builders.py:157,169,184`
- §3.2 — insert — ambiguity — `default_declared_at` rendered in `Z`-suffixed 3-fractional-digit form — `routes/builders.py:188`
- §3.3 — insert — ambiguity — `email` required non-blank with no length ceiling and its at-sign test runs after `full_name`/`state_code`; buyer row carries only the three declared fields plus `id`/`created_at` — `routes/parties.py:22-31`
- §3.9 — insert — ambiguity — deactivation `reason` required non-blank and not stored on the panel row — `routes/parties.py:60`
- §4 — insert — ambiguity — routing ignores a trailing slash — `app.py:65`
- §5 — revise — MISMATCH — "Every error response carries one of the identifiers below" was false; documented the three out-of-catalogue envelope fallbacks `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 — `app.py:77-91`

Partition files walked: all nine in full. `errors.py` alone produced no edit — its 54 identifier->status pairs are byte-for-byte the §5 table. Cross-checks done read-only against `store.py`, `calc.py` and the five pass-2/3 route modules; deliberately did NOT assert a universal "fields are checked in narrative order" rule because `routes/parties.py:27` defers the at-sign test, so that pin was scoped locally to §3.3.

### Pass 2 summary (verbatim)

Size: 457 lines / 105,846 chars -> 457 lines / 108,230 chars (+2,384 chars; no new lines). Counts: 10 ambiguity-pins, 1 mismatch-revision.

Changes:
- §2.3 (list ordering) — revise — ambiguity — coverage-term listing tie-break beyond `start_date` pinned to `created_at` then insertion order — `store.py:138`, `routes/policies.py:224`
- §2.8 (closing paragraph) — insert — MISMATCH — the ladder put ownership/segregation rungs 3-5 ahead of the rung-6 404 unconditionally; impl can only run them once the row is loaded, so the 404 wins everywhere except builder submission and home enrollment (where the comparison is against the supplied identifier text). Verified across all seven route modules — `routes/transfers.py:29-32`, `routes/policies.py:134`, `routes/builders.py:58`, `routes/policies.py:45`
- §3.3 (enrollment payload) — insert — ambiguity — a `closing_date` later than the clock date is `ERR_INVALID_REQUEST`, tested after every other field's shape check — `routes/policies.py:62`
- §3.3 (minting coverage) — revise — ambiguity — the three BASE terms are inserted workmanship -> systems -> structural, which (shared `start_date`) fixes their listing order — `calc.py:186-205`
- §3.3 (endorsement overlap) — insert — ambiguity — the overlap scan covers same-type terms of any `term_kind` and any `status`, `ELAPSED`/`LIMIT_EXHAUSTED` included — `routes/policies.py:185-190`
- §3.4 (billing) — revise — ambiguity — `invoice_reference` is any string incl. blank, validated then discarded; the premium axis is tested before the coverage axis — `routes/policies.py:118-124`
- §3.4 (payment) — revise — ambiguity — `payment_reference` likewise validated then discarded; no coverage-axis check, so a `VOIDED` policy still accepts payment of an `INVOICED` premium — `routes/policies.py:137-141`
- §3.5 (transfer creation) — insert — ambiguity — new row's `documents_reference` is null when omitted (blank counts as supplied) and `decision_reason` starts null — `routes/transfers.py:39,65-75`
- §3.5 (documentation loop) — revise — ambiguity — `reason` is required non-blank and discarded; `documents_reference` on resubmission is required and non-blank — `routes/transfers.py:87,102`
- §3.5 (decision) — revise — ambiguity — `decision_reason` may be blank and is written as null when omitted on both branches; a blank `documents_reference` satisfies the approval precondition — `routes/transfers.py:117-123`
- §3.9 (neutral calendar) — revise — ambiguity — the conflict scan covers every case on the neutral regardless of its `status`, and only the requested window is widened — `store.py:320-331`

Partition walked: `calc.py`, `store.py`, `routes/policies.py`, `routes/transfers.py` — every constant, formula, rounding rule, tier boundary, term/policy/transfer transition, both cascades, the epoch sweep and every validation/error path, with read-only cross-checks elsewhere. No pass-3 endpoint narrative was touched except the one shared `store.neutral_window_conflict` clause.

### Pass 3 summary (verbatim)

Size: 457 lines / 108,230 chars -> 457 lines / 112,621 chars (+4,391 chars, line count unchanged). Final FINALIZED -> COMPLETED delta: +13,177 chars. `cmp` PRD_FINALIZED.md PRD_COMPLETED.md -> DIFFERENT (OK). 24 Edit calls: 20 ambiguity-pins, 4 mismatch-revisions, 1 style repair.

Changes:
- §3.6 — insert — ambiguity — `claimed_amount_cents` has no ceiling; the five body fields validate in listed order; `policy_id` resolution + owner check precede all other fields, while an absent/non-string `policy_id` is `ERR_INVALID_REQUEST` — claims.py:38-52
- §3.6 — insert — ambiguity — term-selection tiebreak extended with "and then by insertion order" — claims.py:65 / store.py:138-140
- §3.6 — insert — ambiguity — intake writes only the claim row; neither policy nor selected term is rewritten, so no other row's `version` moves — claims.py:94-96
- §3.6 — insert — ambiguity — the other three settlement figures stay at 0 until routing runs the rest of the waterfall — claims.py:106-109
- §3.6 — insert — ambiguity — the three assessment fields validate in listed order — claims.py:119-121
- §3.7 — insert — ambiguity — `routing_note` is any string, blank included, any length, validated then discarded — claims.py:144
- §3.7 — insert — MISMATCH — the builder loss-ratio recompute is the one exception to §2.4's cascade rule and never advances the builder's `version` — store.py:149-166
- §3.7 — insert — ambiguity — `response_note` validated blank-included then discarded — claims.py:170
- §3.7 — insert — ambiguity — `completion_date` is a required ISO date, stored nowhere, compared against nothing, future dates accepted — claims.py:187
- §3.7 — insert — ambiguity — `adjudication_note` validated blank-included then discarded — claims.py:201
- §3.8 — revise — MISMATCH — every movement of §3.8 appends one row, but the reserve rewrites of a mediated settlement and a positive arbitration award (§3.9) are the one exception and append no row; plus `memo` blank-included / any-length / null-when-omitted — ledger.py:41,70,109 / store.py:234-238
- §3.8 — insert — ambiguity — the four reserve-entry body fields validate in listed order — ledger.py:24-27
- §3.8 — insert — ambiguity — disbursement carries no from-state precondition; the claim's own `status` is never examined — ledger.py:49-66
- §3.8 — insert — ambiguity — charged term's `version` advances by exactly 1 whether or not the charge exhausts it; response body is the updated claim, not the PAYMENT row — ledger.py:71-83
- §3.8 — revise — MISMATCH — term transitions `OPEN -> LIMIT_EXHAUSTED` "on that same single `version` advance" (removes an implied double bump) — ledger.py:73,77-78
- §3.8 — insert — ambiguity — cascade RELEASE rows carry the paying adjuster's `X-User-ID` as `recorded_by_user_id` — store.py:281 / ledger.py:79
- §3.8 — revise — MISMATCH — term `version` advances by exactly 1 for a reversal's restoration whether or not the term reopens — ledger.py:111-117
- §3.8 — insert — ambiguity — a reversal never examines or rewrites the claim's `status` (a `CLOSED_PAID` claim stays closed); response body is the updated claim — ledger.py:107-120
- §3.9 — insert — ambiguity — the five escalation-opening fields validate in listed order; the strict `window_end` comparison runs only after all five pass; a `prior_case_id` on a MEDIATION request must resolve, must match the claim, and is stored — escalations.py:52-58,82-89
- §3.9 — insert — ambiguity — the six checks are listed by subject, not evaluation order: deadline -> calendar -> predecessor-claim — escalations.py:75-84
- §3.9 — insert — ambiguity — `outcome_recorded_by_user_id` also starts null — escalations.py:96
- §3.9 — insert — ambiguity — `settlement_amount_cents` optional integer, floor 0, required only on SETTLED (`ERR_INVALID_REQUEST` raised before the state check), validated-then-ignored on IMPASSE — escalations.py:116-120
- §3.9 — insert — ambiguity — a settled amount of 0 is legal and no journal row is appended for the reserve rewrite — escalations.py:130
- §3.9 — insert — ambiguity — an impasse on an arbitration-stage case takes the identical path (claim stays ARBITRATION, deadline +30d) — escalations.py:132-135
- §3.9 — insert — ambiguity — `award_amount_cents` required, floor 0, no ceiling (bounded neither by reserve nor term limit); `award_note` discarded; the updated case is the response body of both the award and the session-outcome — escalations.py:152-153,173
- §3.9 — insert — ambiguity — the zero-award RELEASE row carries the acting adjuster's `X-User-ID` — escalations.py:169 / store.py:202-209
- §3.7 — revise — style — em-dash/semicolon clash in the `routing_note` insert repaired — claims.py:144

Verification: partition walked in full (claims.py 251 lines, ledger.py 136, escalations.py 209) with read-only cross-checks against store.py, db.py, validators.py, calc.py, response.py, middleware.py, errors.py, app.py. §3.4's clock narrative already matched `set_clock`/`epoch_sweep` exactly and §4's status-code rule already lists payments among the 200-OK operations — no edit needed. Consistency read of §3.6-§3.9 clean: nothing added contradicts §2.8's validation ladder or pass 2's §3.9 neutral-calendar clause; the two "one exception" claims (§3.7 builder-version, §3.8 journal-row) concern different subjects. Final grep confirms all 26 distinctive inserted phrases present exactly once each. Passes 1-2 territory untouched; no `cp`, no `Write`.

### Orchestrator verification of Step 9

`wc -l -c` on the three PRDs: PRD.md 457/99,233; PRD_FINALIZED.md 457/99,444; PRD_COMPLETED.md 457/112,621. `cmp PRD_FINALIZED.md PRD_COMPLETED.md` reports DIFFERENT, so the scan genuinely ran (a byte-identical PRD_COMPLETED.md would have meant no scan happened). Tail of PRD_COMPLETED.md ends on the complete final row of the §5 error table — no truncation. `grep -ci "scaffold|expert level"` = 0, so neither the generator index nor the difficulty directive leaked into the final contract. `workspace/` holds INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/, sweep.log; `test_helpers/` and `test_suite/` remain at the task root; the only worklog.md in the tree is the orchestrator's at the task root (no cwd-drift stray under workspace/).

Pipeline complete: Step 9 has written workspace/PRD_COMPLETED.md.
