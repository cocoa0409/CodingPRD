# Worklog — task_2378_broadband_consumer_label_service_quality

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2378_broadband_consumer_label_service_quality/` and `tasks/task_2378_broadband_consumer_label_service_quality/workspace/` (pre-allocated name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-02T06:37:20.638Z

All three artifacts are generated and the linter is clean.

## Verdict block (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     14
  §1.8 instances scanned:     21
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  1536

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## SCAFFOLD.yaml (§1.0–§1.7)

14 entities: ServicePlan, FeeLineItem, MethodologyDocument, MeasurementProbe, TestRun, PerformanceAttestation, LabelVersion, LabelTranslation, SubscriberAccount, LabelDisclosure, Complaint, RemediationCredit, RegulatorInquiry, PlanChangeNotice. **55 endpoints**, 12 state machines (parallel shape: publication_state × substantiation_status move independently), 2 OCC rules (`expected_plan_version` on `POST /performance-attestations` and `POST /label-versions`), 10 calculations (round-then-sum percentage-fee itemization, 3000-cent discount cap, PEAK_HOUR_MEDIAN vs ALL_HOUR_P20 typical speeds with 0.80 substantiation margin, both first-year variants, ETF whole-month decay, pricing-phase selector, complaint shortfall/credit, first-match `plan_label_posture`), 18 validation priorities (10–80), 56 error ids, 7 roles with maker-checker SoD on `X-User-ID`.

## §1.8 — depth probe

9 rule_ids × 21 instances (≥2 differentiated each): `dual_variant_calc` (2), `combinatorial_formula` (2), `non_linear_state_machine` (3), `transitive_cascade` (2: five-hop and four-hop), `priority_pair_validation_conflict` (3 distinct category pairs), `boundary_precision_check` (3), `cross_entity_state_dependency` (2), `resource_temporal_overlap` (2), `compensating_invariant` (2).

## §1.9 — breadth probe

72 instances across the 9 guide sections — **50 with full `test_recipe`s + 22 `excluded_because` stubs** citing the §1.8 instance that already covers the corner:

| section | real | stubs |
|---|---|---|
| entities | 12 | 0 |
| state_machines | 9 | 7 |
| calculations | 6 | 8 |
| validations | 8 | 4 |
| endpoints | 4 | 1 |
| errors | 4 | 0 |
| rbac | 4 | 0 |
| cross_cutting_complexity_layers | 2 | 2 |
| consistency_model | 1 | 0 |

All 93 instance names are unique across the union of both design files. `claim_type` values are drawn only from guide rows; `bulk_action` is skipped because no bulk endpoint is declared, and the two non-guide complexity layers (`version_pinning_on_approval`, `selector_policy`) are exercised through `variant_selection` / `effective_label_selection` claims rather than invented layer rows.

## Coverage audit notes

- **Error catalogue: 56/56 triggerable.** A trailing comment block in `SCAFFOLD_CORNER_DESIGN.yaml` maps every id to its triggering instance(s), marked `[1.8]`/`[1.9]`; stubs are never counted as triggers. 43 ids are reached from §1.9, 13 only from §1.8 (e.g. `ERR_PROBE_COOLDOWN_CONFLICT`, `ERR_LABEL_WINDOW_OVERLAP`, `ERR_INSUFFICIENT_SAMPLES`, `ERR_REOPEN_WINDOW_EXPIRED`).
- Both §1.2.1 OCC rules have their own stale-version test; the instance also pins that an accepted attestation create is itself a plan write, so a client cannot reuse the version it just used.
- Design corrections made while grounding literals: on FIBER300 the ALL_HOUR_P20 download margin is 0.7933 (< 0.80) and can never certify, so `label_pins_the_variant_of_its_certified_attestation` uses a separate `VARIANT280` plan where both variants certify (0.8571/0.8214 vs 0.8500/0.8000); `ERR_LABEL_NOT_SUBSTANTIATED_FOR_FILING` was made reachable by broadening its condition to `attestation_id is null OR substantiation_status != SUBSTANTIATED`.
- Every formula-derived assert is an author-computed literal (e.g. 6766/3766 intro, 10628/7628 post-promo, 78264/101436 first-year, 11681/8681 after the 8999 PATCH, 83988/95988 on the no-promotion plan, credits 942/500/942 → balance 2384, ETF 12000 → 10000 → 0), and probe windows are kept disjoint and cooldown-safe so no incidental `ERR_PROBE_COOLDOWN_CONFLICT` fires.

## Step 3: Copy shared files — 2026-09-02T06:37:20.638Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T06:52:08.750Z

PRD generated at `workspace/PRD.md` — 470 lines, ~11,850 words. Ends at §5 as required.

## Section list

**§1 Introduction** (3 paragraphs)

**§2 Global Specifications** (12 subsections, 9 of them domain-derived at §2.4+):
2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Record Identity, Versioning and the Disclosure Archive · 2.6 Reference Resolution Order · 2.7 Money, Rounding and Percentile Precision · 2.8 Drafting Against a Plan Snapshot: Optimistic Concurrency · 2.9 The Plan Disclosure Posture Gate · 2.10 Segregation of Duties · 2.11 Order of Rejection · 2.12 Conserved Derived Quantities

**§3 Business Logic & Workflows** (9 subsections):
3.1 Defining a Service Plan and Its Fee Itemisation · 3.2 Measurement Infrastructure · 3.3 Recording Measurement Runs and Withdrawing Them From the Evidence Pool · 3.4 Attesting Typical Speeds and Certifying the Claim · 3.5 Drafting a Consumer Label · 3.6 Translating, Publishing, Archiving and Withdrawing a Label · 3.7 The Retail Surface · 3.8 Consumer Complaints, Investigation and Remediation · 3.9 Regulator Dockets and Evidence Filings

**§4 Endpoint Definitions** — 55 rows, 4 columns. **§5 Error Code Catalogue** — 56 rows, 2 columns.

## Coverage audit, scaffold §1.1–§1.7

- **§1.1 (14 entities / 157 fields)** — all 157 field names appear as exact standalone backticked tokens. `LabelDisclosure` is correctly documented as the only entity without `updated_at`/`version` (§2.5).
- **§1.2 (12 machines / 38 transitions)** — all 38 expressed, including both `LabelVersion` dimensions as independent walks, the 5-hop invalidation cascade plus its non-hop `evidence_gap` consequence, the 4-hop uphold cascade plus its non-hop `upheld_complaint_count` consequence, both compensations (label withdraw predecessor restore; credit void balance recompute), the `RegulatorInquiry` fork-join, all 4 `*_to_WITHDRAWN` complaint transitions, and the 5 `label_posture` re-evaluations.
- **§1.2.1 (2 concurrency rules)** — both in §2.8 naming write operation, `expected_plan_version` and `ERR_STALE_PLAN_VERSION` (412).
- **§1.3 (10 calculations)** — all expressed with pinned orders: round-then-sum on fee lines, gross→benefit→net ordering, round→floor→ceiling on credit amount, ETF keyed on the *source* plan.
- **§1.4 (18 priority tiers)** — full ladder in §2.11; every `check` clause landed (verified the long priority-20 conditional list, priority-55 temporal set, priority-60 (a)/(b)/(c) geometry, priority-70 nine prerequisites).
- **§1.5 (55 endpoints)** — table verified programmatically against the scaffold: method, path, order and authorised-role sets all match. All 48 `side_effects` items across 31 endpoints traced into prose.
- **§1.6 (56 errors)** — all 56 ids and HTTP statuses match exactly; no extras, no omissions.
- **§1.7 (7 roles)** — §2.1 translates `identity`: six opaque operator roles, `Subscriber` as `entity_backed:SubscriberAccount`, with the 12 scoped operations enumerated.

Note: the scaffold's §1.5 header comment says "52 endpoints" but the actual list contains **55**; the table uses the real 55.

## Zero-Silence note (one gap found and repaired)

`ERR_LABEL_INVALID_STATE`'s condition covers a translation *added* under a non-DRAFT label, not only one verified. First draft stated the precondition on verification only; §3.6 now states it for both add and verify.

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 157 required, 157 present, 0 missing
- endpoints[].request_body: 86 required, 86 present, 0 missing
- endpoints[].query_params: 18 required, 18 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 18 checked, 18 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_plan_version + error_id all named), 0 missing
- state_machines[].transitions: 38 checked, 38 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 56 checked, 56 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 48 checked, 48 expressed, 0 missing
- entities[].fields[] structured content: 4 checked (samples elements, fee_itemization entries, methodology_snapshot, required_locales), 4 reconstructible from prose, 0 missing
- sibling-branch symmetry: 15 groups checked, 15 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 895
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-02T07:37:24.364Z

Test infrastructure and suite are complete and audit-clean.

## Files written

**`test_helpers/`** (9 files): `__init__.py`, `types.py` (7 roles + 30 enums + 14 TypedDicts), `api_client.py` (55 endpoint methods), `api_errors.py` (all 56 error ids + HTTP status map registered with the framework validators), `constants.py` (PRD thresholds, clock defaults, pinned reference sample pool + both metric variants), `test_users.py` (per-role identities incl. second identities for the two maker-checker controls, plus `make_subscriber_headers`), `factories.py` (28 payload builders), `assertions.py` (17 domain assertion helpers), `fixtures.py` (48 setup helpers + `build_reference_environment`).

**`test_suite/`**: `conftest.py` plus 14 test files — **156 test functions, 186 collected cases**.

| file | tests |
|---|---|
| test_01_label_pricing_disclosure.py | 6 |
| test_02_typical_speed_attestation.py | 11 |
| test_03_measurement_runs_and_evidence_cascade.py | 14 |
| test_04_label_publication_lifecycle.py | 9 |
| test_05_complaint_investigation_and_remediation.py | 14 |
| test_06_regulator_dockets_and_filings.py | 7 |
| test_07_entity_contracts.py | 12 |
| test_08_state_transitions.py | 34 |
| test_09_derived_figures.py | 8 |
| test_10_validation_gates.py | 8 |
| test_11_endpoint_journeys.py | 9 |
| test_12_rejection_conditions.py | 8 |
| test_13_role_authorization.py | 7 |
| test_14_cross_cutting_consistency.py | 9 |

## Coverage

- **Queue A (Difficulty):** 21/21 instances translated, every one with ≥2 tests. 0 skipped.
- **Queue B (Corner):** 50/50 non-stub instances translated, every one with ≥1 test. 0 skipped. All 22 `excluded_because:` stubs emitted no tests, and all 22 `difficulty_instance:` cross-references were verified to resolve to a real instance under the claimed `rule_id`.
- **Tagging:** every test carries exactly one `Design:` line as the last docstring line; 0 untagged, 0 dual-tagged, 0 stub-tagged, 0 unknown tags.
- **Citations:** every docstring contains a ≥8-word verbatim, whitespace-normalised substring of `workspace/PRD.md`.
- **Prohibited content:** no `scaffold`/`§1.x`/`Table N` vocabulary and no `pytest.mark.skip`/`skipif`/`xfail` anywhere in `test_suite/` or `test_helpers/`.
- `pytest --collect-only` succeeds with zero errors and zero warnings.

## Audit notes — yaml literals that could not be reconciled with the PRD

Sub-assertions were dropped or replaced by the PRD-derived value; no instance was lost, and nothing was weakened beyond the specific unreconcilable literal.

1. `combinatorial_formula/percentage_fee_rounding_order_pinned_round_then_sum` — yaml asserts `monthly_total_post_promo_cents == 10428` (self-flagged as wrong: "correct value is 10628"); that instance's own 3-fee setup actually yields 9928, and the figure is non-discriminating for round-then-sum anyway. Replaced with the discriminating per-line literals (260, 169) plus the PRD's phase-total identity.
2. `combinatorial_formula/discount_benefit_evaluation_order_after_percentage_fees` — `net_monthly_post_promo_cents == 7628` presumes gross 10628; the setup gives 6928. Kept `discount_program_benefit_post_promo_cents == 3000` and asserted net = gross − benefit structurally.
3. `errors/technical_packet_filing_on_an_unsubstantiated_label_rejected` — yaml claims the cascade clears `attestation_id`; PRD §3.3 hop 4 says no such thing. Asserted only `substantiation_status == UNSUBSTANTIATED`, `publication_state == PUBLISHED`, posture `FROZEN`.
4. `errors/fee_itemization_incomplete_blocks_publish` — yaml keeps drift true / posture `RESTRICTED` after publish; PRD §3.6 clears drift on publish → `OPEN`. Asserted the PRD outcome.
5. `endpoints/disclosure_history_readable_from_both_directions` — asserts `disclosed_first_year_total_cents` on a disclosure row, a field the PRD does not define. Literal dropped; a global `state=RECEIVED` count was also narrowed by `complaint_id` to avoid assuming an empty DB.
6. `rbac/subscriber_cannot_reach_another_accounts_records` — expects `disclosed_net_monthly_cents == 6766`; PRD §3.7 copies the label's `net_monthly_intro_cents` (3766) for an INTRO-phase account. Asserted 3766. Its trigger `e5` (`GET /complaints?account_id=<peer>`) was **dropped as not uniquely derivable** — the PRD never says whether a peer filter is 403 or silently scoped; the instance is still covered by its other five denials.
7. `calculations/attestation_pool_excludes_invalidated_and_foreign_runs` — yaml annotates `ERR_NO_ELIGIBLE_TEST_RUNS` as 422; PRD §5 registers 409. Asserted the id only (status cross-checked against the PRD-registered 409).
8. `validations/uniqueness_is_checked_after_schema_conformance` — yaml annotates `ERR_INVALID_REQUEST` at 409; PRD maps it to 400. Used the PRD status. Its arm `e5` (second `en-US` translation on a PUBLISHED label) was dropped because §2.11 puts State (rung 6) before Uniqueness (rung 12), so the PRD uniquely derives `ERR_LABEL_INVALID_STATE` there, not a uniqueness error; the remaining five collision arms carry the instance.
9. `entities/create_service_plan_initialises_every_derived_field` and `.../computed_fields_are_derived_not_accepted_from_input` — yaml says 6 `fee_itemization` rows; deriving §3.5 from the five reference fee lines gives 8 (each `ALWAYS` recurring line itemises under both phases). Asserted the PRD-derived (phase, fee_code, label_category, amount) set; all monetary literals (3766 / 6766 / 7628 / 10628 / 9900 / 78264 / 101436) reconciled exactly.
10. `entities/flat_topology_cross_reference_integrity` — yaml expects `ERR_METHODOLOGY_NOT_PUBLISHED` for an attestation citing a DRAFT document, but §2.11 puts evidence sufficiency (step 14) before referential prerequisites (step 15), so `ERR_NO_ELIGIBLE_TEST_RUNS` is the derivable answer. That sub-assertion was dropped; the run-level and inquiry-level triggers were kept.
11. Two instances (`validations/complaint_must_cite_a_label_covering_the_observed_date`, `state_machines/complaint_triggers_absent_from_the_transition_list_rejected`) assert `investigation_cycles == 1` on a path with no info-request cycle; PRD §3.8 increments only on the `INFO_REQUESTED → UNDER_INVESTIGATION` resume, so a PRD-only implementer reaches 0. The absolute value was not asserted (one test asserts the counter is unchanged across each rejected call instead).
12. `state_machines/complaint_triggers_absent_from_the_transition_list_rejected` also expects 201 for adding an `es-MX` translation to a PUBLISHED label, which §3.6 forbids. The same rule is reached by adding while DRAFT and verifying after publish → `ERR_LABEL_INVALID_STATE`.

Minor deliberate robustness choices: server timestamps are compared as parsed instants rather than raw strings where the PRD pins three fractional digits only for `created_at`/`updated_at`; four-decimal ratios use `pytest.approx(abs=0.0001)`; unobservable negatives (no list endpoint for methodology documents; `created_at`/`updated_at` cannot diverge under a pinned clock) were asserted as far as the API allows, with explanatory messages.

One helper edit was made after the subagents finished: `test_helpers/types.py` `TestRunStatus` now carries `__test__ = False` so pytest does not try to collect the domain enum as a test class (this removed the only collection warning).

## Step 6: Generate implementation — 2026-09-02T07:37:24.364Z

Verification is complete. Both smoke passes ran green against a freshly booted server, and the endpoint set matches the PRD one-to-one.

## Files written

All under `workspace/implementation/` (22 files, ~3,300 lines of Python):

```
start.sh                 guarded pip install, exec python3 app.py, 0.0.0.0:$PORT (default 10000)
requirements.txt         flask
app.py                   create_app(), blueprint registration, ApiError/HTTPException/Exception handlers
db.py                    Store with 14 empty dicts, logical clock, ISO helpers, _seq ordering
errors.py                ApiError + all 56 error IDs + HTTP_STATUS + fail()
response.py              meta envelope (req_<20 alnum> + clock timestamp), success/success_list/failure
middleware.py            7 roles, authorize(), require_own_account()
validators.py            field coercion/bounds, pagination_params(), paginate()
serializers.py           public projection (strips _internal keys), derived pricing_phase
lookup.py                12 FK resolvers + left-to-right nested resolution
services/calculations.py pinned constants, Decimal ROUND_HALF_UP, nearest-rank percentiles, 9 calculations
services/reconcile.py    conserved-quantity recomputation (§2.12)
routes/{clock,service_plans,measurement,labels,accounts,complaints,regulator,notices}.py
```

## Endpoint count

**55 implemented**, exactly matching the 55 rows of the PRD §4 table (a machine diff of method+path found zero real differences; the scaffold header's "52" undercounts). Distribution: measurement 13, complaints/credits 12, labels 9, accounts 5, plans 5, notices 5, regulator 5, clock 1.

## Verification performed

Two end-to-end scripted passes (server relaunched fresh for each). Pass 1 walked plan → 3 fee lines → methodology publish → probe → test run → attestation → certify → draft → translate → verify → publish → account → disclosure → complaint (triage/request-info/investigate/resolve UPHELD) → credit void → regulator docket (2 filings + close) → plan-change notice (acknowledge/effect after clock advance) → run invalidation cascade, plus ~20 negative cases. Pass 2 covered label supersede/archive-truncate, withdraw-and-restore, draft-window overlap, posture gating, the audit flag at 2 credits, posture FROZEN at 3 upheld complaints, flat-tier capping, DISMISSED-no-credit, and the reopen window/cap.

Numeric pins that came out exactly as PRD §3.5 / §3.9 specify: round-then-sum fee itemisation (167 vs 266 cents on the same 3.33% line at two price points), the 3,000-cent discount cap, promo-weighted first-year total 66,498, `PEAK_HOUR_MEDIAN` = 920.0 over the 4 in-window samples with p95 latency 18 by nearest rank, shortfall ratio 0.5652 → SEVERE, pro-rata credit 895, notice_days 45, and the inclusive 30-day reopen boundary.

## PRD passages I had to interpret

1. **`created_at` tie-breaks.** The logical clock makes `created_at` non-unique, so every "ordered by `created_at` ASC" rule uses an internal monotonic insertion counter (`_seq`) as the tie-break. Never serialized.
2. **Ladder vs. referential order on `POST /performance-attestations`.** §2.11 puts evidence sufficiency (step 14) before referential prerequisites (step 15), so an empty eligible pool answers `ERR_NO_ELIGIBLE_TEST_RUNS` before `ERR_METHODOLOGY_NOT_PUBLISHED` is considered. The latter stays reachable via `POST /test-runs`.
3. **`early_termination_fee_cents` is required** on plan creation (§3.1 prose + the scaffold's endpoint input list beat the entity-level `default: 0`).
4. **Duplicate-code rejections** (`fee_code`, `doc_code`, `probe_code`, `account_code`, translation `locale`) return `ERR_INVALID_REQUEST` at **400** — the §4 status catalogue wins over the scaffold's 409 grouping. Only `plan_code` and `docket_number` have dedicated 409 codes.
5. **Which record a posture gate reads on notices**: the account's *current* (source) plan, not the target plan.
6. **Version-bump policy** is exactly §2.12's enumeration — notably *no* plan version bump on fee-line-item creation, even though it recomputes draft-label figures.
7. **Accessibility check split on disclosures**: the account-need↔format rule runs before label selection, the "non-`STANDARD_WEB` requires WCAG_AA" clause after it (unreachable in practice, since publish already demands WCAG_AA).
8. **Withdraw restore** needs the pre-truncation `effective_until`, so publish stashes it on the archived predecessor under an internal key.
9. **`pricing_phase`** is derived at read time rather than stored, so it tracks the clock without version churn.
10. **Subscriber list scoping**: on `GET /complaints` and `GET /plan-change-notices` a mismatched `account_id` query param answers `ERR_ACCOUNT_SCOPE_VIOLATION`; otherwise results are silently narrowed to the caller. `GET /subscriber-accounts` excludes the Subscriber role entirely per §4, making its scope check unreachable.
11. **Query-string enum filters are not validated** — an unknown value yields an empty page; only pagination bounds raise.

## Step 7: Run tests and iterate — 2026-09-02T11:35:00.000Z

Clean sweep achieved on the first iteration — no changes were needed to the artifact.

## Summary

**Iterations run:** 1 (one full 8-round parallel stability sweep).

**Sweep result:** all 8 concurrent rounds green — `total 186, passed 186, failed 0, errors 0, skipped 0` in every round (156 test functions, 186 collected cases including parametrizations). Round duration ~1770–1784 s each under 8x concurrency. No flakiness: the union of non-passing tests across all 8 rounds is empty, so there was no diagnostic protocol to apply.

**Tests deleted:** none. No test failed in any round, so no test entered STEP 1.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Integrity checks performed on the inherited artifact** (to confirm the green sweep isn't an artifact of a weakened suite):
- 0 occurrences of `pytest.mark.skip` / `skipif` / `xfail` anywhere in `test_suite/` or `test_helpers/`.
- 0 occurrences of file/DB persistence (`sqlite`, `json.dump`, `pickle`, `shelve`, `/tmp/`, write-mode `open`) in `workspace/implementation/` — storage is in-memory dicts only, so `start.sh` re-invocation under `--isolation per-test-server` wipes all state, which the per-test restarts across 8 concurrent rounds exercised 1,488 times without a single state-leak failure.
- The sweep was launched under `setsid nohup` as required; no round showed the `Terminated`/simultaneous-death reaping signature, and all 8 results files are valid JSON with matching totals.

**Notable context:** the task's `worklog.md` documents a prior generation pass that had already reconciled 12 SCAFFOLD-vs-PRD literal conflicts (dropping or replacing non-PRD-derivable sub-assertions, e.g. a `disclosed_first_year_total_cents` field the PRD never defines, and a ladder-order case where §2.11 puts evidence sufficiency before referential prerequisites). Those corrections were already on disk; my sweep confirms the resulting artifact is stable, not merely lucky.

### Orchestrator verification note (resume run)

Independently re-read all 8 `results.*.json` after the subagent exited: every file reports `total 186 / passed 186 / failed 0 / errors 0 / skipped 0`. Step 7 is therefore complete under the "all 8 rounds report passed == total" criterion.

Filesystem forensics on the inherited (partially-complete) task dir: mtime scan shows exactly two artifacts modified after the Step 5/6 worklog timestamps (07:37) — `test_suite/test_07_entity_contracts.py` (07:54) and `test_suite/test_13_role_authorization.py` (08:59). No `.py` file under `workspace/implementation/` was modified after 07:40. So a prior, unrecorded Step 7 iteration made `test_suite/`-only PRD-alignment edits in those two files and zero implementation fixes. No diff of those edits survives (the dirs are untracked in git), so their content could not be reconstructed for a Step 8 hand-off.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T11:36:00.000Z

Skip condition honoured. This Step 7 run exited on its first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes, so there is no `<step_7_diff>` to target and no site where the implementation pinned a behaviour that a Step 7 failure proved `PRD.md` had left open.

Reasoning recorded for the prior-run edits: the two `test_suite/` files touched by the earlier unrecorded iteration would in principle be Step 8 material, but (a) no diff of those edits exists to inline as `<step_7_diff>`, and (b) the only durable record of that reconciliation work lives in the Step 5 worklog entry, whose content is SCAFFOLD-derived — inlining it into a Step 8 prompt would leak scaffold literals into PRD prose, which the pipeline explicitly forbids (Step 8 MUST NOT read SCAFFOLD*.yaml or worklog.md). Rather than fabricate a hand-off, the gap is closed by Step 9, whose mandate is strictly larger: a full exhaustive `PRD`-vs-`implementation/` scan that pins every residual silence or mismatch regardless of whether a test ever signalled it. Step 9 was additionally pointed at the behaviours those two test files exercise (entity contracts / derived-field initialisation, and role-authorization scoping) so the specific areas are not merely covered incidentally.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T11:46:00.000Z

All 18 changes are single-line, in-paragraph substitutions; no sections added, no lines added or removed.

## Summary

**`workspace/PRD_COMPLETED.md` produced** (source: `workspace/PRD.md`, since `PRD_FINALIZED.md` does not exist).

- **Line counts:** 469 → 469 (unchanged; every edit is an in-paragraph substitution)
- **Char delta:** 87,193 → 92,484 (**+5,239**)
- **Changes:** 18 total — **13 ambiguity-pins**, **5 mismatch-revisions**

Verified independently: the impl's 56-entry `HTTP_STATUS` map is byte-identical to PRD §5 (no extra/missing ids, no status disagreements), and all 55 route/role pairs in `routes/*.py` match the §4 table exactly.

### Changes

- **§2.1 role scoping** — revise — *mismatch* — dropped "listing accounts" from the scoped set (impl refuses `Subscriber` there with `ERR_UNAUTHORIZED` at ladder step 2, never scoping); pinned that the two scoped *list* endpoints refuse only when a foreign `account_id` filter is explicit and otherwise silently self-scope; pinned that per-label disclosure listing is unscoped for `Subscriber` — `middleware.py:50`, `routes/accounts.py:77`, `routes/complaints.py:132`, `routes/notices.py:99`, `routes/labels.py:383`
- **§2.3 ordering** — insert — *ambiguity* — `created_at` ties broken by insertion order; unparseable/unknown filter values match no records rather than erroring — `db.py:142`, `routes/labels.py:144`
- **§2.5 timestamps** — insert — *ambiguity* — client-supplied instants echoed verbatim without normalisation; three-fractional-digit form applies only to server-written stamps; accepted ISO 8601 laxity — `db.py:16`, `validators.py:130`
- **§2.5 write-only fields** — insert — *ambiguity* — `change_justification`, withdrawal `reason`, `priority_note`, `reopen_reason`, `withdraw_reason`, filing `summary` are required but never persisted — `routes/service_plans.py:115`, `routes/labels.py:260`, `routes/complaints.py:154`, `routes/regulator.py:88`
- **§2.5 version increments** — insert — *ambiguity* — disclosure recording and notice effecting also bump `SubscriberAccount.version`; a no-op recomputation bumps nothing (draft-label figures) — `routes/accounts.py:155`, `routes/notices.py:150`, `services/reconcile.py:97`
- **§2.9 posture triggers** — revise — *mismatch* — "after a complaint is resolved" → "after a complaint is *upheld*"; dismissal recomputes nothing — `routes/complaints.py:226`
- **§2.11 step 5** — revise — *mismatch* — "twelve scoped operations" → "eleven" — `middleware.py:50`
- **§3.1 required_locales** — insert — *ambiguity* — each tag 2–16 chars — `validators.py:163`
- **§3.1 amendment** — insert — *ambiguity* — price move requires a genuinely different value; coherence rules re-checked against the merged record; a no-attribute amendment is legitimate — `routes/service_plans.py:147`
- **§3.5 fee_itemization** — insert — *ambiguity* — entry has exactly 4 keys; one entry per applicable phase (so `ALWAYS` + intro price yields two); phase-major ordering (INTRO → POST_PROMO → ONE_TIME), line order within phase; empty array when nothing itemisable — `services/calculations.py:99`
- **§3.5 excluded categories** — revise — *mismatch* — `EARLY_TERMINATION`/`DATA_OVERAGE` excluded from the `fee_itemization` array itself, not just from the totals — `services/calculations.py:105`
- **§3.7 disclosure locale** — insert — *ambiguity* — 2 to 16 characters — `routes/accounts.py:96`
- **§3.7 accessibility gate order** — revise — *mismatch* — the format-vs-`WCAG_AA` sub-rule is evaluated after label selection, so no-label-in-effect yields `ERR_LABEL_NOT_EFFECTIVE_FOR_SERVICE_DATE` rather than the accessibility code — `routes/accounts.py:117`
- **§3.7 notice posture** — insert — *ambiguity* — the gate reads the *source* plan, never the target — `routes/notices.py:43`
- **§3.7 notice disclosed net** — insert — *ambiguity* — null when the target plan has no published label — `routes/notices.py:56`
- **§3.8 dismissal** — insert — *ambiguity* — nothing written to the plan: no posture recompute, no `version` bump — `routes/complaints.py:226`
- **§3.8 credit void** — insert — *ambiguity* — complaint not written (no `version` bump) when `remediation_credit_cents` already reads 0 — `routes/complaints.py:372`
- **§3.9 response_due_at** — insert — *ambiguity* — a deadline at or before the clock is `ERR_INVALID_REQUEST` at ladder step 3, ahead of the `complaint_id` lookup — `routes/regulator.py:32`

### Orchestrator verification note

Confirmed on disk: `PRD_COMPLETED.md` is 469 lines / 92,484 chars vs `PRD.md` 469 lines / 87,193 chars, and `diff` reports exactly 18 changed line-pairs (36 `<`/`>` lines) — matching the reported 13 ambiguity-pins + 5 mismatch-revisions with zero structural additions. The file's tail is the complete §5 error table, so the document is not truncated.

Pipeline complete: Steps 1–7 and 9 ran, Step 8 skipped under its stated skip condition.
