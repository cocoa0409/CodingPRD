# Worklog — task_2673_coupon_clearinghouse_redemption_settlement

## Step 1: Create task directory — 2026-09-04T04:44:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2673_coupon_clearinghouse_redemption_settlement` and its `workspace/` subdirectory. Index 2673 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed and no index was allocated locally (32 pipelines run concurrently on this host, so auto-allocation would collide).

## Step 2: Scaffold generation — 2026-09-04T06:55:00.000Z

Generated the three scaffold artifacts from the scenario-2673 description plus the
scaffold-generator specification only (no sibling task under `tasks/` was inspected):

- `SCAFFOLD.yaml` (§1.0–§1.7): 12 entities, 11 state machines, 2 §1.2.1 concurrency
  rules, 13 calculations, 57 validation rows over 35 priority levels, 55 endpoints,
  51 error codes, 6 roles. Primary complexity `ledger_reconciliation`, secondary
  `compliance_audit`; layers dual_variant_calculation, cascading_side_effects,
  derived_field_reconciliation, optimistic_concurrency; topology flat; state-machine
  shape parallel; role model segregation_of_duties; consistency model immediate.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8): 9 rule ids, 23 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9): 9 sections, 93 instances (66 with full
  test recipes, 27 `excluded_because:` stubs pointing at the §1.8 instance that
  already covers the corner).

`scaffold_lint.py` reports `VERDICT: clean lint` (1353 calls scanned across §1.8+§1.9).

## Step 2 (orchestrator record — verbatim subagent summary) — 2026-09-04T06:52:00.000Z

All three artifacts are complete and the lint is clean.

### Files (all at `/home/ubuntu/github/CodingPRD/tasks/task_2673_coupon_clearinghouse_redemption_settlement/`)
- `SCAFFOLD.yaml` — 3532 lines, §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2800 lines, single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5971 lines, single top-level key `scaffold_corner_design`
- `worklog.md` — Step 2 entry appended

No sibling `task_*/` directory was listed, globbed, grepped or read at any point; the design comes only from the scenario text and the generator skill (`SKILL.md` + `references/claim-extraction-guide.md`).

### §1.0–§1.7 counts
12 entities · 11 state machines · 2 §1.2.1 concurrency rules · 13 calculations · 57 validation rows across 35 priority levels · 55 endpoints · 51 error codes · 6 roles.
Profile: primary `ledger_reconciliation`, secondary `compliance_audit`; layers `dual_variant_calculation, cascading_side_effects, derived_field_reconciliation, optimistic_concurrency`; topology `flat`; state-machine shape `parallel`; role model `segregation_of_duties`; consistency `immediate`. Two SoD walls (lot adjudicator ≠ dispute resolver; statement issuer ≠ payment releaser) and an explicit "ClearinghouseAdmin is not a hierarchical override" note.

### §1.8 — 9 rule ids / 23 instances
`dual_variant_calc` 2 · `combinatorial_formula` 2 · `non_linear_state_machine` 3 · `transitive_cascade` 2 (depths 4 and 4) · `priority_pair_validation_conflict` 3 · `boundary_precision_check` 3 · `cross_entity_state_dependency` 3 · `resource_temporal_overlap` 3 · `compensating_invariant` 2.

### §1.9 — 9 sections / 93 instances (66 full recipes + 27 `excluded_because:` stubs)
entities 16 (16/0) · state_machines 22 (15/7) · calculations 17 (10/7) · validations 19 (10/9) · endpoints 5 (5/0) · errors 4 (4/0) · rbac 4 (3/1) · cross_cutting_complexity_layers 5 (2/3) · consistency_model 1 (1/0). Only the 9 legal `section:` values and row-derived `claim_type:` values from the claim-extraction guide are used.

### Verification
- `scaffold_lint.py`: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (55 endpoints, 12 entities, 23 §1.8 + 66 §1.9 instances, 1353 calls scanned).
- Programmatic checks I wrote: all 27 stub `difficulty_instance` citations resolve to an existing §1.8 instance **and** the correct `rule_id`; stubs carry only `name/claim_type/grounds/excluded_because` (no `test_recipe`); all 66 real instances carry the full seven-point contract; zero duplicate `name`s across the union of both design files; every `grounds:` path resolves against `SCAFFOLD.yaml` (entities/fields, calculations/constants, error ids, endpoint method+path, validation priorities, roles, concurrency rule ids); no forbidden concurrency vocabulary.

### Fixes made while auditing
- Lint initially reported 12 violations, all inside deliberately negative §1.9 probes. The lint's sanctioned escape hatch is the instance-name pattern, so four instances were renamed (`..._input_ignored`, `..._returns_401_...`, `admin_cannot_stand_in_for_...`); one real defect surfaced and was fixed: a hardcoded `expected_retailer_version: 1` replaced by a captured `${rv}` (check (e) applies even to negative tests).
- `endpoints.POST_retailers_id_fraud_rescore` → `endpoints.POST./retailers/{id}/fraud-rescore`.
- Closed the cosmetic priority gap: `ERR_PAY_DATE_NOT_REACHED` renumbered 36 → 35, with the two prose/grounds references updated; priorities are now 1..35 contiguous.
- Earlier sessions also fixed six bogus `grounds:` paths, several wrong entity field names, one wrong `total_count`, one wrong HTTP verb and two garbled prose passages, plus a YAML indentation break.

### Design adjudications
- **SoD split across files:** wall 2 (issuer cannot release) is already asserted inside §1.8 `cross_entity_state_dependency / statement_release_gated_on_invoice_funded`, so §1.9 carries it as a stub and spends a real instance on wall 1 (the finalizing analyst barred from resolving that lot's dispute, keyed on `adjudicated_by_user_id` rather than on the role).
- **`ERR_STATEMENT_ALREADY_PAID` needed a two-statement invoice:** with a single statement the invoice bubbles to RECONCILED and priority 8 would answer instead, so the fixture bills two submissions onto one invoice and releases only the first, leaving the invoice FUNDED.
- **Not-found sweep from an opaque staff role** so priorities 1, 2 and 4 all pass and each family's own 404 code is what answers; this closes the nine existence codes no other fixture touched.
- **OCC instances stay one-per-§1.2.1-rule** and use the endpoint's own prior write to invalidate the token (statement issue bumps `Submission.version`), plus the rescore case asserts the version advances even though no score field changes value — the trap for a "no change, no bump" implementation.
- **`ERR_EMPTY_SUBMISSION` probe keeps a SUSPENDED retailer** to show the answer does not change, because `POST /settlement-statements` is outside the priority-10 `applies_to` list.
- **Duplicate-barcode ownership is decided by `adjudicated_at`,** not capture order, so the later-captured item can win.
- **Dispute fixtures use multi-lot submissions** so `rejected_lot_count != sorted_lot_count` and no auto-rescore/suspension cascade interferes.
- **The reinstated-sampled-lot instance deliberately does not assert `Offer.accepted_redemption_count`** — the scaffold leaves the counter's treatment for reinstated SAMPLED lots ambiguous, and pinning it would over-specify.

Orchestrator verification: all three files present and non-empty (182K / 186K / 354K); each tail ends at a real structural boundary (a complete YAML scalar inside a closed list), not mid-sentence.

## Step 3: Copy shared files — 2026-09-04T06:52:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: PRD generation — 2026-09-04T07:12:00.000Z

PRD generation is complete.

### Output
`/home/ubuntu/github/CodingPRD/tasks/task_2673_coupon_clearinghouse_redemption_settlement/workspace/PRD.md` — **453 lines, 113 KB**. Built in 13 chunked `cat >>` appends; ends at a genuine boundary (last row of the §5 error table), with no audit footer and no contract-report block. The withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, and no sibling task directory was read.

### Section list
- §1 Introduction
- §2 Global Specifications (11 subsections): 2.1 Role-Based Access Control · 2.2 API Response Structure (verbatim block, byte-identical — verified) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Versioning · 2.5 The Logical Clock and Its Sweeps · 2.6 Money, Rates and Rounding Discipline · 2.7 Optimistic Concurrency Control · 2.8 Cascade Discipline and Deterministic Ordering · 2.9 Ledger Identities · 2.10 Read Access, Filters and Nested Creation Paths · 2.11 The Validation Ladder (all 35 levels)
- §3 Business Logic (9 subsections): 3.1 Market Onboarding · 3.2 Coupon Design and Barcode Minting · 3.3 Intake, Count Verification, Sorting and Capture · 3.4 Adjudication · 3.5 Lot Finalization, Valuation and Handling Fees · 3.6 Fraud Scoring and Retailer Standing · 3.7 Disputes and Reinstatement · 3.8 The Settlement and Funding Chain · 3.9 Digital Coupon Clearing
- §4 Endpoint Definitions (4-column table, 55 rows)
- §5 Error Code Catalogue (2-column table, 51 rows)

### Coverage (mechanically verified)
- **Entities**: all 12 represented; `PurchaseDataRecord`'s reduced field set (`id` + `created_at` only, no `updated_at`/`version`) stated explicitly in §2.4.
- **Endpoints**: 55/55 in the §4 table, exact method+path set equal to the scaffold's (set diff empty), zero duplicates.
- **Error codes**: 51/51 in §5 with scaffold-exact HTTP statuses (set diff empty); all 51 also appear in §2/§3 prose, not only in the table.
- **Validation priorities**: 35 levels / 57 rules — every rule's `error_id` present in the §2.11 ladder, including both facets of the six path-vs-body `*_NOT_FOUND` pairs (levels 3 and 6), plus the four documented outranking notes.
- **Calculations**: all 13 narrated with operators in natural language and constants as literals (`SAMPLE_RATE` as "a tenth"/×10÷100, `CLEARING_FEE_PCT` as "1.5 percent"), each with a worked example.
- **State machines**: 11 machines / 57 transitions — every from→to pair co-occurs in a paragraph that names both states; all state names appear in prose.
- **Roles**: all 6, with entity-backed vs opaque identity, both SoD walls, and the "ClearinghouseAdmin is not a hierarchical override" paragraph.

### Hard Contract reports (message only)
- **Contract 1 — Field-Name Coverage: PASS.** 126 identifiers (112 entity fields + endpoint input/path identifiers). Two independent passes: 126/126 appear as standalone backticked tokens; 0 missing. Response-shape and envelope identifiers (`full_count_gross_face_value_cents`, `sampled_gross_face_value_cents`, `lot_count`, the three sweep counters, `limit`/`offset`/`total_count`/`has_more`) also verified present. All non-null input defaults verified co-located with their field name.
- **Contract 2 — Rule Coverage: PASS.** Priority ordering and `applies_to` scopes in §2.11; both OCC rules (`expected_submission_version` → `ERR_STALE_SUBMISSION_VERSION`, `expected_retailer_version` → `ERR_STALE_RETAILER_VERSION`, both 412) in §2.7 and level 7; every cross-entity cascade narrated hop by hop with ordering keys; all sibling forks given symmetric treatment (finalize `VALIDATED`/`LOT_REJECTED`, funding full/short, dispute `UPHELD`/`OVERTURNED`, digital `MATCHED`/`UNMATCHED`, both fraud variants, both valuation variants, both barcode families); all 27 write endpoints' side-effect lists narrated.
- **Contract 3 — §3 Path Purity: PASS.** 904 backtick tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combinations; also zero unbacktick'd method verbs or path-like strings in §3 body text.

Scaffold self-conflicts resolved conservatively and consistently (offer-withdraw lot scope → `SORTED`; dispute window anchored on `adjudicated_at`; fraud rescore on submission close only in the all-lots-rejected branch; `valuation_method` = `FULL_COUNT` unless at least one lot sampled); the `verify-count` `declared_count >= 1` precondition is stated in prose without inventing an error ID, since the scaffold nominates none.

Orchestrator truncation check (per the known doc-generator failure mode): `grep -n '^#'` shows all five top-level sections present through §5, and `tail -6` shows six complete pipe-table error rows ending with `| ERR_PAY_DATE_NOT_REACHED | 422 |`. The file ends at a real section boundary, not mid-sentence. No regeneration needed.

## Step 6: Implementation generation — 2026-09-04T08:05:00.000Z

(Steps 5 and 6 were launched concurrently in a single orchestrator message, per the
skill's isolation requirement; Step 6 returned first. Resume-mode note: Steps 2, 3 and 4
were already satisfied on disk — SCAFFOLD.yaml / SCAFFOLD_DIFFICULTY_DESIGN.yaml /
SCAFFOLD_CORNER_DESIGN.yaml all present and non-empty, workspace/INSTRUCTION.md present,
workspace/PRD.md complete at 453 lines ending on the last row of the §5 error table —
so none of them were re-run.)

Verbatim subagent summary:

Implementation complete and fully smoke-verified. Server processes were launched on explicit high ports and killed by captured PID only (no `pkill` was ever run); all smoke ports are now free.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_2673_coupon_clearinghouse_redemption_settlement/workspace/implementation/`

| file | lines |
|---|---|
| `app.py` | 98 |
| `db.py` | 181 |
| `errors.py` | 84 |
| `middleware.py` | 143 |
| `response.py` | 84 |
| `validate.py` | 119 |
| `services/calc.py` | 180 |
| `services/domain.py` | 531 |
| `routes/parties.py` | 241 |
| `routes/offers.py` | 185 |
| `routes/intake.py` | 478 |
| `routes/adjudication.py` | 126 |
| `routes/settlement.py` | 393 |
| `routes/disputes.py` | 242 |
| `routes/digital.py` | 206 |
| `routes/clock.py` | 73 |
| `routes/__init__.py`, `services/__init__.py` | 0 |
| **total Python** | **3364** |

Plus `requirements.txt` (`flask>=2.0`) and executable `start.sh` (reads `$PORT` default 10000, binds `0.0.0.0`, `exec python3 app.py` in the foreground, pip install only when Flask is missing). All 16 modules pass `ast.parse`. No `__pycache__` left behind.

## Endpoint coverage: 55 / 55

Diffed Flask's `url_map` against the 55 rows of the PRD §4 route table: **0 missing, 0 extra** (the only non-table route is the framework 404/405 handler). Storage is in-memory dicts only — the persistence audit found no `sqlite`, `open()` write, `pickle`, or `/tmp` usage, and every `start.sh` re-invocation was observed to wipe state (duplicate-GS1-prefix collisions vanished on each reboot; a cold boot returns `total_count: 0`).

## Pinned PRD examples verified against a live server

Barcode minting `8111234560012305261231003` (25 digits) and `51234560012305003` (17 digits); sample plan 40→FULL_COUNT / 41→5 / 50→5 / 60→6; extrapolation 5-of-6 → 0.8333 → 50 units → 2500 cents; **per-lot fee rounding 403 + 105 = 508** (and 507 when a single 63-unit lot is summed first, exactly as the PRD contrasts); count variance 63/62 → 1.59 pass, 63/61 → 3.17 fail, 400/408 → 2.00 pass; holdback waterfall 3150 + 508 → 3658, band 0.00 + add-on 0.03 → 110 → net 3548; clearing fee 47 and invoice total 3705; pay dates NET_30 → 2026-08-31, NET_15 → 2026-08-16 Sunday → 2026-08-17, NET_45 → 2026-09-15; clip expiry `min(clip+30, expiry+5)` → 2026-08-15; **fraud rolling 0.00 vs lifetime 14.00** on identical rows (dup rate 10.00 from weighted mass 0.5/5.0); the four-test ladder (COUNTERFEIT > EXPIRED > DUPLICATE > MISREDEEMED, `INSUFFICIENT_QUALIFYING_UNITS` still recording the short basket, null serial skipping step three, `claimed_units × purchase_requirement_units` arithmetic); adjudication-order-driven duplicate ownership; item `created_at` + k ms; SCHEDULED→HELD→SCHEDULED funding-hold cycle; reverse-funding restoring the ledger exactly; RECONCILED bubble-up; UPHELD/OVERTURNED dispute cycles with the 2-round info cap; all three clock sweeps returning 1/1/1; both SoD walls; and all 35 ladder levels I could reach, including the pinned precedence cases (SoD > funding > pay date; state > overfunding; billability > billing buffer).

## Ambiguous passages and the interpretations chosen

1. **Ownership scope (§2.1 vs §2.11 level 4).** Enforced strictly on FK fields physically present on the row — `retailer_id` for Retailer callers, `manufacturer_id` for Manufacturer callers, with `retailer_id` resolved through the submission for submission-lots/coupon-items/disputes. Consequences: no ownership check on `GET /manufacturers/{id}` or `GET /retailers/{id}` (those rows carry no such FK), no manufacturer-side check on statements, and list endpoints are **not** auto-scoped to the caller.
2. **Body-FK ownership ordering.** Level 4 nominally precedes level 6, but a body FK can only be owner-checked once resolved, so ownership runs immediately after the *owning* FK resolves (always the first FK checked: `manufacturer_id`, then `retailer_id`, then `offer_id`).
3. **Version bumps.** At most one `version` increment per row per HTTP request (thread-local touched-id dedupe), which is what makes "issuance increments `Submission.version` by 1" literally true when the same request also recomputes that submission.
4. **`declared_count == 0` on verify-count** → `ERR_COUNT_VARIANCE_EXCEEDED` (variance is undefined; the alternative was `ERR_INVALID_STATE_TRANSITION`).
5. **`/valuation`** forces *all* lots of the submission through both variants (per "forcing every lot through"), not only settleable ones; it writes nothing.
6. **Clock echo** returns the canonical 3-fractional-digit form (`2026-09-01T00:00:00.000Z`) rather than the caller's literal string, and `api_request_timestamp` is drawn from the logical clock, not wall time.
7. **Dispute resubmit** appends the new narrative to the old with a `"\n"` separator.
8. **Rescore of a SUSPENDED retailer** cannot change status (no legal transition out of SUSPENDED per §3.6's enumerated moves), but `handling_fee_tier` is still set unconditionally on the 70.00 boundary, per "separately and on the same boundary".
9. **`rejected_lot_count`** counts only lots whose status is exactly `LOT_REJECTED`; a `DISPUTED` lot is not counted.
10. **Empty `items: []`** on capture is accepted (201 with an empty array, nothing created) — the PRD bounds elements, not the array.
11. **Negative `provisional_net_cents`** is refused with `ERR_INVALID_REQUEST` on issuance (explicit in §3.8); `max(0, …)` is used only as a safety net inside the cascade recompute of already-issued statements.
12. **Ledger fields** (`funded_total_cents`, `disbursed_total_cents`, `unpaid_balance_cents`) are recomputed from stored rows rather than incrementally adjusted, so the §2.9 identities hold after any rollback or cascade.
13. **PRD-vs-scaffold conflicts resolved in favour of PRD prose:** dispute window anchored on `lot.adjudicated_at`; offer-withdrawal hop 1 touches only `SORTED` lots and never values them (items stay `CAPTURED`); the close-time fraud rescore fires only in the total-loss branch; no separate "appeal already live" error (the `LOT_REJECTED` state guard at level 8 covers it).
14. **Unmatched routes/methods** return `ERR_NOT_FOUND` (404) — a code not in the PRD's 51, needed because the spec defines no envelope for an unrouted request.

## Step 5: Unit test generation — 2026-09-04T09:20:00.000Z

(Launched concurrently with Step 6 in the same orchestrator message; returned second.)

Verbatim subagent summary:

All 23 difficulty instances and all 66 non-stub corner instances are now translated; the suite is complete at **150 tagged tests** across 22 files, with both audits clean.

## Files written (task root — nothing under `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2673_coupon_clearinghouse_redemption_settlement/test_helpers/` (Stage 1, unchanged this pass): `__init__.py` 145, `api_client.py` 425, `api_errors.py` 137, `assertions.py` 317, `constants.py` 197, `factories.py` 271, `fixtures.py` 465, `test_users.py` 98, `types.py` 224, `_audit_citations.py` 64.

`/home/ubuntu/github/CodingPRD/tasks/task_2673_coupon_clearinghouse_redemption_settlement/test_suite/`: `conftest.py` 19; queue A — `test_01` 283/6 tests, `test_02` 240/6, `test_03` 458/9, `test_04` 403/9, `test_05` 371/9, `test_06` 447/10, `test_07` 479/10, `test_08` 396/9, `test_09` 571/13; queue B — `test_10_entity_contracts` 332/8, `test_11_entity_field_contracts` 466/8, `test_12_state_machine_corners` 622/9, `test_13_state_machine_cascades` 764/9, `test_14_encoding_and_intake_math` 304/4, `test_15_money_and_scoring_math` 520/6, `test_16_uniqueness_and_intake_gates` 277/5, `test_17_precedence_and_ceilings` 414/5, `test_18_endpoint_contracts` 454/5, `test_19_error_catalogue_corners` 278/4, `test_20_rbac_corners` 251/3, `test_21_concurrency_corners` 161/2, `test_22_consistency_corners` 108/1.

## Coverage

- §1.8 (queue A): **23 of 23** rule instances, 81 tests, every instance >=2 tests.
- §1.9 (queue B): **66 of 66** non-stub instances, 69 tests — entities 16, state_machines 15, calculations 10, validations 10, endpoints 5, errors 4, rbac 3, cross_cutting 2, consistency 1. The 27 `excluded_because:` stubs were deliberately not translated.
- Verified mechanically: every tag resolves to a real instance, no dual tags, no stub translated, no unknown tags.
- `python3 test_helpers/_audit_citations.py` → "tests with exactly one trailing Design line: 150", zero TAG/CITE problems, exit 0. `pytest --collect-only` collects 150. `pyflakes` clean (only re-export noise in `__init__.py`/`conftest.py`). No docstring or comment mentions the scaffold or a scaffold section.

## Instances skipped

**None.** Every non-stub instance passed the PRD-first two-condition filter, so no gaps were left and no placeholder/xfail was emitted.

## Instances adapted where the design recipe contradicted the PRD (PRD wins)

New this pass:
- `endpoints/bulk_image_capture_...` and `endpoints/lot_list_filters_and_paginates...` — recipes assert newest-first listings; PRD line 85 makes `created_at` **ascending** the default and names only the manufacturer and retailer listings as exceptions. Asserted ascending (also used as the array-order proof for capture).
- `errors/every_not_found_code_in_the_catalog_is_reachable` — recipe asserts `data` null; the PRD error envelope carries `error_id` and `message` *inside* `data`. Asserted nine distinct `error_id`s plus a non-blank `message`.
- `cross_cutting/fraud_rescore_refuses_a_retailer_version_token...` — recipe asserts `last_rescored_at == "2026-08-01"`; the PRD writes a logical-clock **instant**. Asserted a millis timestamp beginning `2026-08-01`.
- `consistency_model/every_cascaded_money_field...` — same correction for the lot's `adjudicated_at`.

Carried from earlier passes (already recorded in the files): six instances whose recipes expected an automatic fraud rescore where the PRD rescores only on a total-loss close; three `test_13` cascade adaptations; `all_rejected_submission_...` (`counterfeit_rate` is 50.00, not 100.00, because the pool is every adjudicated coupon of the retailer); `fraud_pool_excludes_captured_items...` (dropped the "settled totals still null" claim — the PRD starts money fields at 0); `offer_code_uniqueness_survives_withdrawal...` (`soup50` is a 400 `ERR_INVALID_REQUEST`, since the code charset is uppercase-only).

## Step 7: Test/fix iteration loop — 2026-09-04T09:46:30.000Z

Orchestrator-side independent verification (recorded because a Step 7 subagent's clean-sweep
claim is not self-evidencing): I read the per-round counts out of the results files myself, at
two points, without relying on the subagent's report. At 09:24 UTC all 8 rounds read 141/150
with an identical failure set — deterministic, so the 9 failures were real defects and not the
CPU-contention or sweep-reaping artefacts this host is prone to. At 09:36 UTC, after the
subagent's fixes, all 8 rounds read 150/150, and `grep -c 'def test_'` over test_suite/ still
totalled 150, confirming the 9 failures were fixed rather than deleted away.

The subagent removed `results.*.json` and `sweep.log` on exit. Since the pipeline's output
contract lists `results.{1..8}.json` as a deliverable, the orchestrator re-ran one final
8-round sweep under `setsid nohup` to regenerate those artifacts (result recorded in the
Step 7 artifact-regeneration note below).

Verbatim subagent summary:

Done. All 8 parallel rounds pass 150/150.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (each round: 150 tests, `--isolation per-test-server`, launched under `setsid nohup`, joined with `wait`).

Iteration 1: every round reported 141/150 with an identical 9-test failure set (union size 9 — fully deterministic, no flakiness signal, no `Terminated`/same-instant-death pattern).

### Tests deleted
None deleted outright. One assertion removed under STEP 1c (partial coverage):
- `test_18_endpoint_contracts.py::test_02_the_valuation_read_returns_both_variants_and_writes_nothing` — removed the two-line `assert_rate_equals(projected["sampled_accepted_rate"], "1.0000", …)` assertion (and the now-unused import). **COMPUTED-FIELD SILENCE**: PRD §2.6 says only "Extrapolated unit-accept rates used during lot valuation are computed to 4 decimal places" and §3.5 describes the rate purely as an unnamed intermediate ("First the unit accept rate is the `accepted_qty` divided by the `sample_size`, rounded half up to four decimal places"); no PRD sentence names a persisted lot field `sampled_accepted_rate`, and the submission-lot field list omits it. The rule that drove the assertion (two-step rounding of the extrapolation) is still fully covered by the surviving `assert_lot_valuation(projected, …, 41, 2050, 287)` and the 450-vs-2250 both-variant checks.

### Fixes to `test_suite/` (test bugs — all made the tests *more* faithful to PRD)
- `test_02_combinatorial_fee_and_holdback_formulas.py` — tests 04/05/06: `validate_success(api.issue_statement(...))` defaulted to expecting HTTP 200 on a creation endpoint. PRD §4: "Creation endpoints — those that bring a new resource into existence — return HTTP 201." Added the explicit `, 201`, matching the convention already used at `test_11:378`, `test_21:56/81`, `test_22:99`.
- `test_05_validation_priority_conflicts.py` — test 09 asserted `limit=50` on a listing called with no `limit`. PRD §2.3: "`limit` controls page size: it defaults to 10". Changed to `limit=10`.
- `test_16_uniqueness_and_intake_gates.py` — test 05 built lots of 6 + 4 against a `verified_count` of 10, which per PRD §3.3 ("once the running sum of `counted_qty` over the submission's lots exactly equals the submission's `verified_count`, the submission advances `COUNT_VERIFIED` → `SORTED`, which closes it to any further lots") leaves the submission `SORTED`, so the ladder's rung 8 own-entity-state check (`ERR_INVALID_STATE_TRANSITION`) correctly answers before rung 26 (`ERR_LOT_COUNT_OVERFLOW`) — the fixture made the asserted rung unreachable. Reordered so the overflow probe (now `counted_qty` 5 against a running sum of 6, i.e. 11 > 10) fires while the submission is still `COUNT_VERIFIED`, then created the 4-coupon lot. Every downstream assertion (`sorted_lot_count` 2, `SORTED`, `declared_face_value_cents` 500, `sample_size` 4, `captured_item_count` 2, `ERR_LOT_CAPTURE_COMPLETE`) is preserved unchanged.
- `test_19_error_catalogue_corners.py` — test 02 asserted the expired offer's `barcode_payload` equals `CANONICAL_DATABAR_PAYLOAD`, which encodes expiry `2026-12-31`, while the test's own offer is created with `expiration_date="2026-08-31"` (it has to expire between the two clock advances). Replaced with `databar_payload("038000", 50, 1, "2026-08-31", 30)` so the expected payload is derived from the offer the test actually creates.
- `test_20_rbac_corners.py` — test 01 called `build.submission(retailer_id, 1)`, omitting the two required positional postmark-window arguments (TypeError at collection-independent runtime). Supplied `"2026-07-01", "2026-07-31"`.

### Fixes to `test_helpers/`
None. (Notably, the money-as-JSON-strings factory pathology was checked for and is absent — all money literals in `factories.py` are plain ints.)

### Fixes to `implementation/`
- `workspace/implementation/errors.py` (`ERROR_STATUS`), `workspace/implementation/routes/adjudication.py` (`get_item`, `adjudicate_item` — both `mw.fetch` calls), `workspace/implementation/routes/digital.py` (`get_redemption_event`): renamed `ERR_ITEM_NOT_FOUND` → `ERR_COUPON_ITEM_NOT_FOUND` and `ERR_EVENT_NOT_FOUND` → `ERR_REDEMPTION_EVENT_NOT_FOUND`. PRD §2.11 rung 3 and §5 name these codes verbatim: "`ERR_COUPON_ITEM_NOT_FOUND` (404) on the coupon-item read and adjudicate routes … `ERR_REDEMPTION_EVENT_NOT_FOUND` (404) on the digital-redemption-event read route." Uniquely determined, and `test_helpers/api_errors.py` already used the PRD names.

No implementation check was removed or weakened; no endpoint, field, side effect or seeded data was added; storage remains in-memory dicts only.

### Final sweep (per-round passed/total)
| round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| result | 150/150 | 150/150 | 150/150 | 150/150 | 150/150 | 150/150 | 150/150 | 150/150 |

0 failed, 0 errors, 0 skipped in every round. Sweep artifacts (`results.*.json`, `sweep.log`) were removed afterwards so `implementation/` ships clean.

## Step 7 (artifact regeneration + third independent verification) — 2026-09-04T09:58:30.000Z

The Step 7 subagent deleted its own `results.*.json` on exit, so the orchestrator re-ran one
more full 8-round sweep under `setsid nohup` purely to regenerate the deliverable artifacts,
staging them in `workspace/sweep_results/` so the concurrently-running Step 8 subagent would
not trip over 46 KB of test-result JSON while walking `implementation/`. They are moved into
`workspace/implementation/` at the end of the pipeline.

This is now the third time an all-green sweep has been observed on this artifact, twice by the
orchestrator directly: rounds 1-8 all report `passed=150 / total=150, failed=0, errors=0`. No
`Terminated` pattern, no same-instant round death, no load-induced connection failures.

## Step 8: PRD finalization — 2026-09-04T09:58:00.000Z

Verbatim subagent summary:

## Outcome: `PRD_FINALIZED.md` is byte-identical to `PRD.md`

Every one of the six `<step_7_diff>` items traces to a **test-side fixture/expectation bug against behavior PRD already uniquely determines**, or to an **implementation bug that Step 7 fixed *toward* the PRD** (so PRD was already right). No PRD silence and no PRD/impl mismatch survives. I manufactured no edits.

- `PRD.md`: 453 lines / 113226 bytes. `PRD_FINALIZED.md`: 453 lines / 113226 bytes. Delta 0.00%. `md5sum` identical (`939edd90…`), `cmp` clean.
- Changes: none.

## Per-item adjudication (subject → impl paths enumerated → verdict)

**1. Deleted assertion `projected["sampled_accepted_rate"]` (test_18 test_02) — the claimed COMPUTED-FIELD SILENCE.**
Subject: whether a lot (or the valuation read) exposes a persisted extrapolated-rate field. Enumerated: `implementation/routes/intake.py:239-266` (the complete lot row literal at creation), `implementation/routes/intake.py:117-146` (the valuation read's response dict), `implementation/services/calc.py:119-134` (`lot_valuation`, `extrapolated_rate`), `implementation/routes/adjudication.py`, `implementation/routes/disputes.py` (finalize / OVERTURNED re-valuation writers), plus a repo-wide grep for `sampled_accepted_rate`/`accepted_rate` across `implementation/`, `test_suite/`, `test_helpers/`.
Finding: **no such field exists anywhere in the implementation.** The rate is a pure local `Decimal` in `calc.lot_valuation` (`calc.py:126`), and `calc.extrapolated_rate` (`calc.py:131`) is dead code with zero callsites. PRD already pins the observable surface exactly: line 145 exhaustively enumerates the valuation read's seven response fields (matching `intake.py:134-146` field-for-field), line 221 enumerates the new lot's fields, line 363 describes the lot read as "resolved valuation variant, projected units and rounded handling fee", and line 111's "Extrapolated unit-accept rates used during lot valuation are computed to 4 decimal places" describes intermediate precision, not a stored field. A fresh implementer reproduces the impl. Kept verbatim; adding a negative claim ("the rate is not persisted") would be gratuitous and would risk narrowing line 111's cross-cutting precision rule.

**2. `test_02` tests 04/05/06 — HTTP 200 vs 201 on `issue_statement`.**
Subject: success status of `POST /settlement-statements`. Enumerated: `implementation/routes/settlement.py:91` (returns 201), and every other creation site for consistency — `settlement.py:273` (invoice), `intake.py:87` (submission), `intake.py:266` (lot), `intake.py:415` (item batch, `array_response(..., 201)`), `intake.py:451` (purchase record); all lifecycle-advance routes (`settlement.py:144/189/363/393`, etc.) return the default 200. PRD line 337 already states creation endpoints return 201 and everything else 200, and line 373 describes the endpoint as issuing a new statement. PRD determines; pure test bug.

**3. `test_05` test 09 — asserted `limit=50` with no `limit` supplied.**
Subject: default page size. Enumerated: `implementation/middleware.py:92-105` (`pagination()`, `limit = 10`, bounds 1..100, `offset = 0`) and `middleware.py:115-117` (`paginate`), which every listing route funnels through (`intake.py:101/281/465`, `offers.py`, `parties.py`, `settlement.py:105`, `disputes.py`, `digital.py`, `adjudication.py`). PRD line 83 already pins "defaults to 10". PRD determines; pure test bug.

**4. `test_16` test 05 — overflow probe fired after the submission had already closed to `SORTED`.**
Subject: precedence of own-entity-state (rung 8) over lot-count overflow (rung 26) on lot creation. Enumerated: `implementation/routes/intake.py:194-266` — the `COUNT_VERIFIED` guard at 203-207 precedes the overflow check at 233-237, and the auto-advance to `SORTED` at 263-264. PRD lines 158 (rung 8, "adding lots to a submission whose `intake_status` is not `COUNT_VERIFIED`"), 176 (rung 26), 149 (first-failing-check-wins) and 221 (running-sum auto-advance closes the submission) jointly determine both the ordering and the fixture's fate. PRD determines; pure fixture bug.

**5. `test_19` test 02 — expected payload constant encoded expiry `2026-12-31` while the offer used `2026-08-31`.**
Subject: barcode minting. Enumerated: `implementation/services/calc.py:82-96` (`barcode_payload`, both families) and its single callsite in `implementation/routes/offers.py` (offer registration, minted once). PRD lines 203-205 pin the six components, widths, zero-padding, `YYMMDD` derivation and both family layouts verbatim, matching `calc.py` digit-for-digit. PRD determines; pure test bug (the test contradicted its own fixture).

**6. `test_20` test 01 — `build.submission()` called without the two required postmark bounds.**
Subject: required-ness of `postmark_window_start`/`_end`. Enumerated: `implementation/routes/intake.py:18-24` (`SUBMISSION_SPEC`, both `required: True`), `intake.py:37-40` (strict start<end), `intake.py:45-56` (half-open overlap scan). PRD line 215 already states both are "required on every submission of either channel" and "the start must be strictly earlier than the end". PRD determines; pure factory-call bug.

**7. Implementation fix — `ERR_ITEM_NOT_FOUND` → `ERR_COUPON_ITEM_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` → `ERR_REDEMPTION_EVENT_NOT_FOUND`.**
Subject: 404 code names on the coupon-item and redemption-event routes. Enumerated: `implementation/errors.py:17,23` (both now 404), `implementation/routes/adjudication.py` (`get_item`, `adjudicate_item`), `implementation/routes/digital.py` (`get_redemption_event`); grep confirms the old names appear nowhere in `implementation/` or `PRD.md`. PRD line 153 (rung 3) and the §5 catalogue rows at lines 412 and 418 already name both codes verbatim with status 404 — this was an impl-side deviation corrected toward the PRD, so the PRD needs no change.

**8. `test_helpers/` — no fixes.** Confirmed independently: no money-as-JSON-strings pathology; nothing to trace.

No PRD sentence was widened, narrowed, reordered or re-scoped, so no NO-NEW-MISMATCH exposure was created for Step 9 to undo. Nothing under `implementation/`, `test_suite/` or `test_helpers/` was touched; the only file written was `workspace/PRD_FINALIZED.md` (via the `cp` in step 0).

Orchestrator note: a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 outcome here and was
verified independently (`md5sum` both `939edd90774c27422fa7208fb7306b53`). Step 7's only
`implementation/` change was two error-code renames that moved the code *toward* prose the PRD
already stated verbatim, and the remaining five items were test-side bugs — so there was no
PRD silence for Step 8 to pin. This does NOT excuse Step 9, which performs the full
implementation-wide scan and is expected to produce a non-identical `PRD_COMPLETED.md`.

## Step 9: PRD completeness scan — plan — 2026-09-04T09:59:00.000Z

`implementation/` is 3364 lines across 16 modules, which is too much for one subagent to scan
exhaustively without silently degrading into a skim (the known failure mode is a
byte-identical `PRD_COMPLETED.md`, i.e. the scan never really ran). Step 9 is therefore run as
three SEQUENTIAL module-partitioned passes over one shared `PRD_COMPLETED.md`. Pass 1 performs
the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 must not, and each pass edits the file the
previous pass left behind.

- Pass 1 — cross-cutting core + parties + offers + clock: `app.py`, `db.py`, `errors.py`,
  `middleware.py`, `response.py`, `validate.py`, `routes/parties.py`, `routes/offers.py`,
  `routes/clock.py`.
- Pass 2 — intake and adjudication: `routes/intake.py`, `routes/adjudication.py`,
  `services/calc.py`.
- Pass 3 — money and downstream: `routes/settlement.py`, `routes/disputes.py`,
  `routes/digital.py`, `services/domain.py`.

## Step 9: PRD completeness scan — 2026-09-04T10:42:00.000Z

Run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`, per the
plan recorded above. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were
explicitly told not to, and each verified the prior passes' edits had survived before exiting.

**Total: 59 edits — 49 ambiguity-pins, 10 mismatch-revisions.** Source `PRD_FINALIZED.md`
453 lines / 113,226 chars → `PRD_COMPLETED.md` 456 lines / 135,740 chars (+22,514 chars,
+3 lines; every pass kept its edits in-paragraph, no new sections). Orchestrator verification:
`md5sum` differs from `PRD_FINALIZED.md` (`79fb557b…` vs `939edd90…`), so the scan genuinely
ran rather than degenerating into the byte-identical no-op failure mode; all five `##` section
headings survive and the file still ends on the last row of the §5 error table
(`| ERR_PAY_DATE_NOT_REACHED | 422 |`), so nothing was truncated.

### Pass 1 — core + parties + offers + clock (19 edits: 18 ambiguity, 1 mismatch)

Verbatim subagent summary:

- **Source:** `PRD_FINALIZED.md` — 453 lines / 113,226 chars. **Result:** 456 lines / 123,955 chars (+10,666 chars, +3 lines). Not byte-identical. No new sections; one new paragraph (§5 preamble) and one new bullet (§2.2); all 110 table rows untouched.
- §2.1 — insert — ambiguity — headers trimmed of whitespace, whitespace-only counts as blank, role matched case-sensitively (so `retailer` → `ERR_UNAUTHENTICATED` not `ERR_FORBIDDEN_ROLE`), `X-User-ID` never checked against a stored row — `middleware.py:37-48`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `response.py:15-16`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the **logical clock**, not wall time; identical across responses between advances; `2026-08-01T00:00:00.000Z` at boot — `response.py:19-23`
- §2.2 — insert — ambiguity — the bulk image-capture call returns `response_type: "array"` with *no* pagination `meta`; underscore-prefixed internal keys stripped from `data` — `response.py:68-75`, `response.py:26-31`
- §2.3 — insert — ambiguity — `limit` outside 1–100, negative `offset`, or non-integer literal → `ERR_INVALID_REQUEST` (400), **not** clamped; `offset` >= `total_count` legal, empty page, `has_more` false — `middleware.py:92-112`
- §2.3 — insert — ambiguity — **`created_at` ties broken by an internal monotonic insertion counter, ascending**; descending listings are the reversal of that full order. Load-bearing because the logical clock only moves on demand, so most rows share `created_at` — `db.py:177-181`, `db.py:144`
- §2.4 — insert — ambiguity — store is empty at boot, nothing seeded; `created_at` taken from the logical clock — `db.py:36-40`, `db.py:136-140`
- §2.4 — insert — ambiguity — **`version` advances by exactly 1 per *request*, not per field write** — `db.py:163-174`
- §2.5 — insert — ambiguity — `current_utc` accepts trailing `Z`, numeric offsets (normalised to UTC) and any fractional-digit count; unparseable → `ERR_INVALID_REQUEST` (400) *before* monotonicity — `db.py:102-121`, `clock.py:19-23`
- §2.5 — insert — ambiguity — dispute-SLA sweep uses `filed_at`'s calendar date; returns the lot only if still `DISPUTED` and writes `reject_reason = DISPUTE_UPHELD`; dispute still withdraws and counts either way; sweep recomputes no submission/statement/retailer figures — `clock.py:56-64`
- §2.6 — insert — ambiguity — decimal fields serialise as **JSON numbers**, so `0.00` renders `0.0` and `0.0300` renders `0.03`; declared places govern rounding, not printing — `response.py:34-35`
- §2.10 — insert — ambiguity — filters are exact, case-sensitive, conjunctive; an unmatched value returns an empty page rather than 400; `digital_enabled` accepts `true/1/yes`/`false/0/no` case-insensitively, else 400; undocumented query params ignored; **no listing endpoint is ownership-scoped** — `middleware.py:120-136`, `parties.py:109-113`, `offers.py:110-119`
- §2.11 L4 — **revise — mismatch** — ownership bites only where the row carries the caller's FK, so `/manufacturers/{id}` and `/retailers/{id}` are readable by any role; and on creation endpoints the effective order is shape (5) → body FK (6) → ownership (4) — `parties.py:97-101,171-175`, `offers.py:57-61`
- §2.11 L5 — insert — ambiguity — absent/empty/`null` body == `{}`; non-object JSON fails; optional field explicitly `null` takes its default; every string field must be non-blank after trim; ints must be JSON ints (bool/float fail), bools must be JSON bools; query params validated at this level; register/activate reject any non-empty body — `validate.py:23-38,89-114`, `middleware.py:73-85`
- §2.11 L7 — insert — ambiguity — both `expected_*_version` fields are mandatory non-negative ints, so missing/non-integer/negative fails at L5 (400) and never reaches 412; a well-formed `0` reaches it and is stale — `parties.py:233`, `settlement.py:28`
- §3.1 — insert — ambiguity — manufacturer-suspend `reason` is required, 1–500 chars, and **not persisted** — `parties.py:63-65,123`
- §3.1 — insert — ambiguity — same rule for retailer suspend/reinstate `reason`; suspending an already-`SUSPENDED` retailer → `ERR_INVALID_STATE_TRANSITION` — `parties.py:199-204,215`
- §3.2 — insert — ambiguity — `DRAFT` is also an inadmissible withdrawal from-state (409); withdrawal carries **no** manufacturer-standing gate, which is how the §3.1 suspension cascade reaches offers — `offers.py:163-184`
- §4 — insert — ambiguity — a trailing slash routes to the same handler — `app.py:29`
- §5 — insert — ambiguity — `ERR_NOT_FOUND` (404) for unknown paths **and for method mismatches** (deliberately not 405), `ERR_INTERNAL` (500) for unexpected failures — neither in the catalogue table; plus the whole-store snapshot/restore that makes "no partial change is persisted" absolute — `app.py:65-89,45-56`

Already-pinned (no change): all 51 `ERROR_STATUS` entries match §5 exactly; pagination mechanics; envelope shapes and 201-on-creation; ladder ordering within every partition endpoint; `id`/timestamps/`version` conventions and `PurchaseDataRecord`'s unversioned row; clock boot value, monotonicity, sweep order, `DISPUTE_SLA_DAYS = 30`; manufacturer creation bounds/defaults/uniqueness; the manufacturer-suspension offer cascade; retailer creation defaults and suspend/reinstate transitions; offer creation spec, register and activate gates; all three listing role/filter sets; clearable states.

### Pass 2 — intake + adjudication + calc (19 edits: 15 ambiguity, 4 mismatch)

Verbatim subagent summary:

- Before: 456 lines / 123,955 chars. After: **456 lines / 128,380 chars** — all edits in-paragraph, on lines disjoint from pass 1's.
- **§2.1** — revise — mismatch — Manufacturer ownership list extended to include submission lots; a lot read is scoped on both sides — `routes/intake.py:273-274`
- **§2.10** — insert — ambiguity — the valuation read spans every lot *whatever its status*, off each lot's currently stored `accepted_qty`/`counted_qty`/`sample_size`, re-adjudicating nothing and pricing no handling fee — `routes/intake.py:121-146`
- **§2.11 L4** — insert — ambiguity — on creation endpoints only the caller's **own** FK must resolve before ownership; remaining body references are looked up afterwards — `routes/intake.py:437-439`
- **§2.11 L5** — revise — mismatch — "the two endpoints that accept no body fields" corrected to **six**: offer registration, offer activation, single-coupon adjudication, lot finalization, statement scheduling, payment release — `routes/adjudication.py:56,77`
- **§2.11 L6** — insert — ambiguity — several body references on one endpoint resolve in the order the level lists them; lot creation reports `ERR_MANUFACTURER_NOT_FOUND` when both manufacturer and offer are unknown — `routes/intake.py:199-202`
- **§3.2** — insert — ambiguity — zero-padding never truncates, so `face_value_cents` 100000 renders six characters and lengthens the payload by one digit — `services/calc.py:84`
- **§3.3** — insert — ambiguity — `postmark_window_start >= end` is a level-5 `ERR_INVALID_REQUEST`, decided before `retailer_id` resolves — `routes/intake.py:39-41`
- **§3.3** — insert — ambiguity — a new submission starts with `sorted_lot_count`/`rejected_lot_count` 0 and `valuation_method` `FULL_COUNT`, recomputed only at close — `routes/intake.py:75-83`
- **§3.3** — insert — ambiguity — `verified_count` bounded 0..1000000 — `routes/intake.py:155-156`
- **§3.3** — insert — ambiguity — a zero `declared_count` recount is refused with `ERR_COUNT_VARIANCE_EXCEEDED` (422), after the state and retailer gates — `routes/intake.py:166-170`
- **§3.3** — insert — ambiguity — `counted_qty` capped at 1000000 — `routes/intake.py:190`
- **§3.3** — insert — ambiguity — `items` required and array-typed and the sole allowed body key, each element a closed six-key object; an **empty** `items` array succeeds with 201/empty array, creates nothing, still bumps the lot's `version` — `routes/intake.py:328-341,384-415`
- **§3.3** — insert — ambiguity — `image_uri`'s 300-char ceiling is enforced only once the value is non-blank, so a whitespace-only value of any length is `ERR_IMAGE_REQUIRED` — `routes/intake.py:350-351,375-376`
- **§3.4** — revise — ambiguity — duplicate-owner ranking gains the §2.3 insertion counter as third tie-break after `adjudicated_at`, `created_at` — `services/domain.py:231-238`
- **§3.4** — revise — ambiguity — basket ranking gains the same tie-break after `transaction_date`, `created_at` — `services/domain.py:258-264`
- **§3.5** — revise — ambiguity — the rejected branch *explicitly writes* `projected_accepted_units` as well as gross and fee to 0 — `routes/adjudication.py:112-116`
- **§3.5** — insert — ambiguity — the extrapolated rate is **not capped at 1**; since `accepted_qty` sums `claimed_units`, multi-unit coupons can project more units than `counted_qty` — `services/calc.py:126-128`
- **§3.5** — insert — mismatch — the `max_redemptions` ceiling and the counter increment both use `projected_accepted_units`, not `accepted_qty`; the test runs *after* the lot is valued and priced, so a refusal rolls that valuation back — `routes/adjudication.py:98-110`, `services/domain.py:171-189`
- **§4 table** — revise — mismatch — the adjudicate row said "five-step ladder" where the ladder has four tests; also pinned that it accepts no body, touches neither the offer counter nor the lot valuation, and never closes the submission — `routes/adjudication.py:52-70`

Already-pinned (no change): submission spec and channel matrix; half-open postmark overlap; check ordering on all six write endpoints; grace-day boundary; `ERR_LOT_COUNT_OVERFLOW` running sum; `sample_plan` and the 40/41 boundary; `count_variance_pct` round-before-compare and its three worked examples; new-lot defaults; `COUNT_VERIFIED → SORTED` on exact equality; per-element `created_at` of clock+k ms; capture ceiling counting elements; `claimed_units`/`serial_number`/`scanned_barcode` bounds; `pos_transaction_ref` 400-vs-422 split; purchase-record immutability; both `lot_valuation` variants and the rate→units→cents rounding order; `sample_size` as denominator; handling-fee tiers and the 403+105=508 per-lot-rounding example; settled totals over `VALIDATED`/`REINSTATED` only; the `accepted_qty >= 1` fork; the total-loss close cascade; the four-rung ladder and each `reject_code`; the global duplicate pool; `claimed_units × purchase_requirement_units`; `INSUFFICIENT_QUALIFYING_UNITS` recording the earliest matched basket.

### Pass 3 — settlement + disputes + digital + domain (21 edits: 16 ambiguity, 5 mismatch)

Verbatim subagent summary:

- 456 lines / 128,380 chars → **456 lines / 135,740 chars** (all edits in-paragraph). File still ends with `| ERR_PAY_DATE_NOT_REACHED | 422 |`.
- §3.2 — revise — mismatch — withdrawal's total-loss close explicitly does **not** rescore the retailer or apply the §3.6 gate; statement recompute spelled out field by field (gross/fee refreshed from the submission's settled totals, offset retained, waterfall re-derived against the retailer's *current* `misredemption_rate`, status and `scheduled_pay_date` untouched), plus the negative-provisional clamp: base floored at 0 so holdback is 0 while `holdback_pct` may still carry the 0.03 add-on and `net_payable_cents` stays negative — `domain.py:380-397, 449-462`
- §3.2 — revise — mismatch — activation no longer claimed to open digital clipping; clipping is gated on `digital_enabled` alone — `digital.py:33-35`
- §3.5 — insert — ambiguity — `valuation_method` scan spans all lots whatever their status — `domain.py:121-126`
- §3.6 — revise — mismatch — the automatic rescore fires only on a **finalization**-driven total-loss close, not the withdrawal cascade's — `domain.py:401-426`, `adjudication.py:125`
- §3.6 — insert — ambiguity — rolling-window cut-off is instant arithmetic (clock time of day included), not date arithmetic — `domain.py:306-308`
- §3.6 — insert — ambiguity — `SUSPENDED` is terminal against scoring, while the tier is re-derived from score alone regardless of status — `domain.py:358-376`
- §3.7 — insert — ambiguity — a lot with null `adjudicated_at` (an `OFFER_WITHDRAWN` lot) is refused `ERR_DISPUTE_WINDOW_CLOSED` and can never be appealed — `disputes.py:56-60`
- §3.7 — insert — ambiguity — filing recomputes nothing on the submission; `rejected_lot_count` still counts the now-`DISPUTED` lot — `disputes.py:87-89`
- §3.7 — insert — ambiguity — `info_request_note` (1–1000) validated but never persisted; resubmitted narrative appended behind a single newline with the bound measured on the fragment only — `disputes.py:124-134, 171`
- §3.7 — revise — mismatch — "newly cleared units" = new `projected_accepted_units` minus the previously stored value; not tested against `max_redemptions`; **offer row untouched and `version` not bumped when the delta is 0** — `disputes.py:223-234`
- §3.7 — insert — ambiguity — reinstated coupons keep `adjudicated_at` and `matched_purchase_record_id`; no statement revaluation, no retailer balance/counter/fraud rescore, submission `settlement_status`/`hold_reason` untouched (a `FRAUD_REVIEW` hold survives) — `disputes.py:214-238`
- §3.8 — insert — ambiguity — negative `provisional_net_cents` check is evaluated **last**, after version, `CLOSED` and `ERR_EMPTY_SUBMISSION` — `settlement.py:41-66`
- §3.8 — insert — ambiguity — statement created with a null `released_by_user_id` — `settlement.py:86`
- §3.8 — insert — ambiguity — scheduling moves the submission strictly from `PENDING` — `settlement.py:140-142`
- §3.8 — insert — ambiguity — invoice period start/end comparison is level 5, before `manufacturer_id` lookup; >200 `statement_ids` is `ERR_INVALID_REQUEST` — `settlement.py:197-213`
- §3.8 — insert — ambiguity — invoice row retains `statement_ids` verbatim in supplied order — `settlement.py:259`
- §3.8 — insert — ambiguity — release moves the submission strictly from `STATEMENT_ISSUED` — `settlement.py:177-181`
- §3.8 — insert — ambiguity — reversal `reason` is 1–500 and never persisted — `settlement.py:370-373`
- §3.8 — revise — mismatch — reversal sets the submission to `HELD`/`FUNDING_SHORTFALL` only from `STATEMENT_ISSUED`, and is literally branch B's cascade re-run (already-`HELD` skipped, `DRAFT` left alone) — `domain.py:482-498`
- §3.9 — insert — ambiguity — offer `status` never consulted on clip creation or redemption ingest; a past-grace clip lands with `clip_expires_at` before `clipped_at` — `digital.py:33-56, 118-122`
- §3.9 — insert — ambiguity — matcher's third tie-break is the §2.3 insertion counter — `digital.py:142-148`

Already-pinned (no change): ledger recomputes forced by §2.9's absolute-sum identities; the holdback six-step waterfall and its three load-bearing orderings; clearing fee 1.5% rounded once over the sum; pay-date terms and the once-only weekend roll; `SETTLEABLE_LOT_STATUSES`; statement billability triple test; billing-period buffer and its non-`REVERSED` scope; `ERR_STATEMENT_LINES_EMPTY` ladder order 14→18→32; branch A touching no statement; `release_funding_holds` selecting only `FUNDING_SHORTFALL`; `RECONCILED` bubble-up; `ERR_STATEMENT_ALREADY_PAID`; funding ladder order; dispute filing field set and `claimed_face_value_cents`; `hold_statements_for_dispute` over `DRAFT`+`SCHEDULED`; info-round cap of 2; UPHELD writing `DISPUTE_UPHELD`; `has_open_dispute` on scheduling; both SoD walls and their ladder precedence; clip expiry as the earlier of validity and offer grace; the 2-live-clip aggregate refusal; the five matcher pool conditions; the ceiling check before the matcher with `UNMATCHED` recorded as 201; per-endpoint role lists and ownership scoping.

Passes 1 and 2's edits were spot-verified intact by pass 3, and pass 3 scoped its §3.7 zero-delta
wording to the reinstatement path so it does not contradict pass 2's finalization pin.

## Pipeline complete — 2026-09-04T10:43:00.000Z

Final artifact inventory (orchestrator-verified):

- `SCAFFOLD.yaml` / `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` — present, non-empty.
- `test_helpers/` 10 modules, `test_suite/` 23 files (conftest + 22 test files), 150 tests.
- `workspace/INSTRUCTION.md`, `workspace/PRD.md` (453 lines), `workspace/PRD_FINALIZED.md`
  (453 lines, byte-identical to PRD.md — legitimate, see Step 8), `workspace/PRD_COMPLETED.md`
  (456 lines, 59 edits, md5 distinct from both).
- `workspace/implementation/` 16 Python modules (3364 lines) + `start.sh` + `requirements.txt`
  + `results.{1..8}.json`, every round `passed=150 / total=150`.
- No `__pycache__`, no stray sweep logs, nothing misfiled under `workspace/`.
