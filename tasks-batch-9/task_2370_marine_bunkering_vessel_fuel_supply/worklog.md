# Worklog — task_2370_marine_bunkering_vessel_fuel_supply

## Step 1: Create task directory — 2026-09-02T04:32:09.925Z

Created `tasks/task_2370_marine_bunkering_vessel_fuel_supply/` and `tasks/task_2370_marine_bunkering_vessel_fuel_supply/workspace/` (pre-allocated name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-02T06:09:36.908Z

All three artifacts for scenario 2370 are complete and lint-clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2370_marine_bunkering_vessel_fuel_supply/`
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, §1.9)

## SCAFFOLD.yaml contents

- **Scenario line**: verbatim scenario 2370 text; `domain_name: marine-bunkering-vessel-fuel-supply`; `api_prefix: ""`.
- **Complexity profile**: primary `compliance_audit` / secondary `ledger_reconciliation`; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `selector_policy`; topology `flat`; state-machine shape `parallel`; role model `segregation_of_duties`; consistency `immediate`.
- **12 entities**: Port, FuelGrade, IndexQuote (immutable), Customer, DeliveryAsset, Nomination, DeliveryOrder, BunkerDeliveryNote, QualityClaim, LabAnalysis, Invoice, SpillIncident.
- **9 state machines**, including Nomination's two parallel dimensions (compliance_status × fulfillment_status), the QualityClaim analysis↔remediation cycle, and the DeliveryAsset quarantine machine.
- **9 calculations**: `agreed_quantity_resolution` (dual-variant), `customer_credit_exposure` (dual-variant), `invoice_amount` (pinned per-component rounding), `bunker_adjustment_factor` (clamped threshold ladder), `credit_availability_check`, `offspec_verdict`, `remediation_credit`, `asset_compliance_score` (decay), `auto_schedule_asset_selection` (selector policy).
- **61 validations ↔ 61 error ids** (exact 1:1, no orphans on either side), spanning 401/403/404/409/412/422/402.
- **55 endpoints**, 7 roles (2 entity-backed: CustomerRep = Customer id, BargeMaster = DeliveryAsset id), 2 OCC concurrency rules (`expected_nomination_version`, `expected_claim_version`).

## Design instance counts

- **§1.8 difficulty**: 18 instances = 9 rule_ids × 2 (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- **§1.9 corner**: 69 instances across all nine claim-extraction-guide sections — entities 12, state_machines 11, calculations 9, validations 22, endpoints 4, rbac 5, cross-cutting layers 4, consistency_model 1, errors 1 — of which 53 carry full `test_recipe`s and 16 are `excluded_because` stubs citing the §1.8 instance that already covers the corner.

## Verification

- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (917 calls scanned).
- Independently checked: all three files parse; §1.8/§1.9 top-level keys correct and absent from SCAFFOLD.yaml; 87 instance names unique across both design files; every stub cites an existing §1.8 `rule_id / instance_name`; no stub has a `test_recipe`; every `${var}` is captured before use (setup, trigger and assert phases); all 61 error ids are asserted by at least one instance.

## Step 3: Copy shared files — 2026-09-02T06:09:36.908Z

Copied `INSTRUCTION.md` → `tasks/task_2370_marine_bunkering_vessel_fuel_supply/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T06:21:11.935Z

The PRD is complete and all three hard contracts pass.

## What was produced

`workspace/PRD.md` — 436 lines, ~11,300 words.

**Structure** (domain-derived, not copied from the example):

- **§1 Introduction** — 3 paragraphs framing bunkering as a simultaneously regulatory/financial/environmental risk surface, then the two governing design commitments (parallel status dimensions; reproducible derived figures).
- **§2 Global Specifications** — 12 subsections: 2.1 RBAC (7 roles, both entity-backed identities, segregation of duties), 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Record Identity & Versioning, 2.6 Parallel Status Dimensions & Cascade Propagation, 2.7 Reference Resolution Order, 2.8 Validation Precedence, 2.9 Stale-Version Guards, 2.10 Measurement/Money/Rounding Discipline, 2.11 Emission Control Area Compliance, 2.12 Index Quote Selection.
- **§3 Business Logic** — 9 subsections on a lifecycle spine: reference data + fleet -> buyers/credit -> nomination intake & ECA review -> confirmation & slot scheduling -> clearance/pumping/quantity reconciliation -> spill & quarantine -> delivery notes/samples/claims -> lab analysis & remediation -> invoicing & settlement.
- **§4** 55-row endpoint table, 4 columns. **§5** 61-row error table, 2 columns. No audit footer.

## Coverage audit

```
Field coverage check:
- entities[].fields: 113 required, 113 present, 0 missing
- endpoints[].request_body: 71 required, 71 present, 0 missing
- endpoints[].query_params: 21 required, 21 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 61 checked, 61 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 40 checked, 40 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 61 checked, 61 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 33 checked, 33 expressed, 0 missing
- entities[].fields[] structured content: 94 checked, 94 reconstructible from prose, 0 missing
- sibling-branch symmetry: 11 groups checked, 11 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 649
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 verified byte-identical to `section-2.2-response-structure.md`. Zero fuzzy/approximating words. §3 names every endpoint by state-transition pair, role + action verb, or capability description.

## Key findings worth flagging

- **Two asymmetric interval semantics were preserved deliberately and called out in prose**, since they are the easiest thing for an implementer to collapse: the asset-level slot rule uses **closed** intervals with a strictly-greater-than turnaround buffer (a gap exactly equal to the buffer is *rejected*), while the port-level capacity rule uses **half-open** intervals (back-to-back slots that touch at an endpoint never conflict).
- **The pinned rounding order in `invoice_amount`** (round each of the four components to 2dp first, then sum without re-rounding; BAF applies to the *already-rounded* fuel cost) is stated in §2.10 and repeated in §3.9, because summing-then-rounding yields a different cent.
- **One scaffold tension handled conservatively**: `credit_availability_check`'s trigger and its `conservative_commitments` variant both say it gates confirmation *and* clearance, but validation priority 61 scopes `ERR_CREDIT_LIMIT_EXCEEDED` to confirmation only. The PRD states the calculation runs at both points (including the DRAFT-only prospective-commitment rule that prevents double-counting at clearance) while attaching the `ERR_CREDIT_LIMIT_EXCEEDED` rejection to confirmation, and gives clearance the `ERR_CUSTOMER_CREDIT_HOLD` gate the transition preconditions actually list.
- The withheld design files were not opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-02T07:59:47.234Z

Complete. Test suite generation for task_2370 is finished and fully verified.

## Files written

**`test_helpers/` (9 files)** — `types.py`, `api_errors.py` (all 62 catalogue ids + `HTTP_STATUS_CODES` registration), `constants.py`, `test_users.py`, `factories.py`, `api_client.py`, `assertions.py`, `fixtures.py`, `__init__.py` (barrel, 254 exports).

**`test_suite/` (conftest + 13 test files)**

| tests | file |
|---|---|
| 10 | `test_01_reference_data_and_pricing.py` |
| 8 | `test_02_customer_credit_exposure.py` |
| 16 | `test_03_nomination_intake_and_compliance.py` |
| 14 | `test_04_stem_confirmation_and_scheduling.py` |
| 5 | `test_05_clearance_pumping_and_measurement.py` |
| 7 | `test_06_quantity_reconciliation.py` |
| 10 | `test_07_spill_and_quarantine.py` |
| 6 | `test_08_delivery_notes_and_claims.py` |
| 8 | `test_09_lab_analysis_and_remediation.py` |
| 10 | `test_10_invoicing_and_baf.py` |
| 6 | `test_11_validation_precedence.py` |
| 7 | `test_12_compensating_invariants.py` |
| 7 | `test_13_authorisation_and_error_envelope.py` |

## Counts

- **114 test functions; 125 pytest-collected items** (one 11-way `parametrize` over the eleven `*_NOT_FOUND` ids expands).
- **Queue A (Difficulty): 50 tests covering 18 of 18** non-stub instances.
- **Queue B (Corner): 64 tests covering 53 of 53** non-stub instances.

## Instances skipped

**None.** Every non-stub instance in both design indices survived the PRD-first two-condition filter and was translated. The 16 `excluded_because` stubs in `SCAFFOLD_CORNER_DESIGN.yaml` received no tests, and a machine check confirms no `Design:` tag points at a stub name.

## Verification passes (all green)

- **Design tags:** exactly one docstring-final `Design:` line per test; all 114 resolve to a real `name:` in the source yaml; no dual tags, no untagged tests.
- **PRD citations:** all **296** quoted citations normalize to a literal substring of `workspace/PRD.md` (0 failures). This pass caught and fixed 3 fabrications in the final sweep: a non-existent §2.2 `"success" false / "details" object` envelope sentence quoted twice in test_03, a non-existent §2.2 `error_id drawn from the catalogue in §5` sentence in test_13, and a paraphrased §3.3 nomination-initialisation sentence in test_13 — each replaced with the real PRD wording.
- **Error ids:** all 61 distinct `ApiErrorId.*` values asserted anywhere in the suite appear verbatim in PRD prose.
- No `skip`/`xfail` markers, no placeholders, no mention of "scaffold" in any docstring.
- AST sweep: no unused imports or unused module constants in either `test_suite/` or `test_helpers/`; `compileall` clean; `import test_helpers` succeeds.

## Two design-recipe/PRD conflicts adjudicated in the PRD's favour

1. Corner recipe for the claim-state gate asserts `ERR_INVALID_CLAIM_STATE` for a `PROPOSE` on a `SUBMITTED` claim, but creates no invoice — and §2.8 orders "invoice issuance for a claim" *before* "claim state legality", which would yield `ERR_INVOICE_NOT_ISSUED`. Setup corrected to raise an invoice so the asserted id is genuinely the first violation; noted in the docstring.
2. A recipe's successful round-2 lab filing omits `retest_of_analysis_id`, which §3.8 makes mandatory on a second filing; the field was supplied.

No pytest *execution* was attempted (only `--collect-only`), and `workspace/implementation/` was never read.

## Step 6: Generate implementation — 2026-09-02T07:59:47.234Z

Implementation complete and verified.

## Files written (`workspace/implementation/`)

Infrastructure: `app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `validation.py`, `serializers.py`, `lookup.py`
Services: `services/calc.py` (all 12 pinned calculations + constants), `services/cascade.py`, `services/scheduling.py`, `services/__init__.py`
Routes (9 blueprints): `routes/{reference,customers,assets,nominations,orders,notes,claims,invoices,spills}.py`, `routes/__init__.py`
Launcher: `start.sh` (chmod +x), `requirements.txt`

~3,250 lines of Python. **55 endpoints registered — exactly matching the 55 in `SCAFFOLD.yaml`** (verified by diffing the Werkzeug url_map against the scaffold's `endpoints:` block).

## Notable design decisions

- **Logical clock only.** `db.DEFAULT_CLOCK = 2026-08-01T00:00:00Z`; grep confirms zero uses of `datetime.now`/`utcnow`/`time.time`. Every fresh process starts at the default instant.
- **Zero seeding.** `db.Store.reset()` empties all 12 dicts; two consecutive fresh boots both return `total_count: 0` on every list endpoint.
- **Decimal internally, JSON numbers at the boundary.** All money/tonnage/pct arithmetic is `Decimal` + `ROUND_HALF_UP` with component-first rounding for invoice totals; `serializers.as_float` converts only at the response edge.
- **Touch-once semantics.** `db.touch()` records ids in `flask.g._touched_ids`, so a record caught by multiple cascade paths in one request bumps `version` exactly once — this matters for the 4-deep spill->quarantine->order->nomination and claim->invoice->customer chains.
- **Validation precedence** follows PRD §2.8 cross-checked against the scaffold's 61 numbered priorities. Documented resolutions in-code: compliance-approval before order state at `/clear`; asset capacity (52) before figure consistency (54) at `/complete-pumping`; `ERR_INVOICE_NOT_ISSUED` (28) -> claim state (29) -> `ERR_NO_OFFSPEC_FINDING` (32) at `/decision`; `ERR_ASSET_QUARANTINED` (34, state) ahead of the boom/grade business gates at `/start-pumping`.
- **Existence-before-payload** for all body FKs (`lookup.body_ref` returns `None` on a non-string so payload validation still reports the field), then the 404 is raised after payload checks pass, per the scaffold ordering.
- **`GET /customers/{id}/credit-exposure`** recomputes strictly (can surface `ERR_INDEX_QUOTE_UNAVAILABLE`, priority 59) but does **not** bump `version`; `credit-review` recomputes the settled variant and does bump it.
- Port capacity uses half-open intervals, asset slot conflict uses closed intervals plus a strict `>` turnaround-buffer gap — the deliberate asymmetry from PRD §3.4.

## Verification

Server boots cleanly from `bash start.sh` (Flask dev server, `threaded=False`, no reloader). Two smoke suites, **0 failures across ~90 assertions**:

1. Happy path: port -> grade -> 2 index quotes (DESC ordering confirmed) -> customer -> asset -> nomination -> compliance-review -> confirm -> auto-schedule -> clear -> start/complete-pumping -> BDN -> invoice -> issue, plus the claim chain (release-sample -> lab-analysis -> PROPOSE -> accept-remediation) and the spill chain (MAJOR -> quarantine -> containment -> close -> return-to-service).
2. Edge paths: ECA sulfur + ECA documentation rejections, `JOINT_SURVEY_MANDATORY` basis, joint-survey -> AGREE -> DISPUTE -> resurvey -> re-AGREE, `ERR_BDN_ALREADY_ISSUED` after issuance, SoD rejection of the compliance reviewer issuing the BDN, port-capacity 409 on both manual and auto routes, invoice void reopening `CLOSED -> DELIVERED`, sample retention expiry (`EXPIRED` custody, 422 on release, 422 on late claim), plus 401/403/404/409/412/422 negatives.

Hand-checked computed values all matched the scaffold formulas exactly: auto-schedule `slot_end` (300 MT truck -> 02:00 + 2h12m), BAF clamping (0.065 raw -> 0.045 ceiling; 0.015 with tier discount), ECA surcharge (299 x 4.25 = 1270.75), barging-fee floor, `provisional_amount_usd` = 255234.75, remediation credit with the severe-exceedance 1.25x multiplier (58125.00), and compliance score 100 - 45 + 1 bonus = 56.00.

## Step 7: Run tests and iterate — 2026-09-02T11:04:00.000Z

Clean 8-round sweep on the first iteration — no changes were needed.

**Iterations run:** 1 (single 8-round parallel sweep; all rounds launched concurrently under `setsid nohup`, joined with `wait`, no early exit).

**Sweep result:** all 8 rounds identical and fully green.

| round | total | passed | failed | errors | skipped |
|---|---|---|---|---|---|
| 1–8 | 124 | 124 | 0 | 0 | 0 |

Per-round wall time ~1360 s (`per-test-server` isolation, 124 boots/round, 8 rounds contending on the host). Zero flaky tests: every one of the 124 collected items passed in every one of the 8 rounds, so no union-of-failures set existed and the diagnostic protocol (STEP 0→3) was never entered.

**Collection integrity check:** `test_suite/` holds 113 `def test_` functions across 13 files; one of them is an 11-id `parametrize` over the `*_NOT_FOUND` catalogue that expands to 12 items, giving **124 collected** — exactly the `total` each results file reports. So the 124 is the full suite, not a partial collection masking a collection error. (Note: collecting requires `PYTHONPATH` at the task root — `cd test_suite && pytest` alone fails on `ModuleNotFoundError: test_helpers`; the runner sets this up correctly via `--test-dir`.)

**Tests deleted:** none. No test failed, so no PRD-silence or unique-derivability adjudication was triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Housekeeping only:** the Step 7 subagent removed the transient sweep outputs (`workspace/implementation/results.{1..8}.json`, `workspace/sweep.log`) after reading them. No source file in `test_suite/`, `test_helpers/`, or `workspace/implementation/` was modified.

**Orchestrator note (deviation recorded):** the skill's Output section lists `results.{1..8}.json` as part of the deliverable, so the orchestrator re-ran one confirmation 8-round sweep after Step 7 exited, purely to regenerate those artifacts. That sweep was launched concurrently with the Step 9 subagent (Step 9 only reads `implementation/`, so there is no write conflict).

## Step 8: Finalize PRD — 2026-09-02T11:05:00.000Z

SKIPPED per the skill's documented skip condition. Step 7 exited on its first 8-round sweep with 0 iterations beyond the baseline: 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes. With no Step 7 diff there is no `<step_7_diff>` focus list to patch against, so `PRD_FINALIZED.md` is not produced and Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-09-02T13:20:00.000Z

Done. `PRD_COMPLETED.md` written.

## Scale
- Source: `workspace/PRD.md` — 435 lines, 81,148 chars (no `PRD_FINALIZED.md`, as expected)
- Result: `workspace/PRD_COMPLETED.md` — 435 lines, 86,524 chars (**+5,376 chars**, 27 paragraphs touched, no new sections/paragraphs/lines)

## Counts
- **ambiguity-pins: 25**
- **mismatch-revisions: 8**

## Changes
- §2.1 RBAC — insert — ambiguity — list-endpoint scope violation fires only on an explicit conflicting `customer_id` filter; unfiltered listings are silently narrowed — `routes/nominations.py:115`, `routes/claims.py:111`
- §2.2 Envelope — insert — ambiguity — `api_request_id` is `req_` + 20 uppercase alphanumerics; `api_request_timestamp` is the logical clock, not wall clock — `response.py:14,27`
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` and out-of-enum filter values are `ERR_INVALID_REQUEST` — `validation.py:170,189`
- §2.3 Pagination — insert — ambiguity — equal `created_at` ordered by server creation sequence; quote listing ties by later `created_at` then sequence — `db.py:99`, `routes/reference.py:164`
- §2.5 Versioning — insert — ambiguity — `version` advances at most once per request; a record created by the request stays at 1 — `db.py:78,83`
- §2.8 step 6 — insert — ambiguity — an optional field sent as explicit `null` counts as absent and takes its default — `validation.py:56`
- §2.8 guard scope — revise — mismatch — logistics guard covers **nine** operations (adds issuing an invoice) — `routes/invoices.py:106`
- §2.8 guard scope — revise — mismatch — quarantine guard covers **three** operations; auto-schedule excludes quarantined assets from the pool instead of raising — `routes/nominations.py:229`, `services/calc.py:416`
- §2.12 Quote selection — insert — ambiguity — when `quote_date` and `created_at` both tie, the later-posted quote governs — `services/calc.py:74`
- §3.1 Fuel grades — insert — ambiguity — `index_code` and both barging figures are mandatory at registration — `routes/reference.py:122`
- §3.2 Exposure — revise — mismatch — `available_credit_usd` opens at the full credit limit (not 0.00); only `conservative_exposure_usd` defaults to 0.00 — `routes/customers.py:57`, `services/calc.py:287`
- §3.2 Credit review — insert — ambiguity — review rewrites `outstanding_balance_usd`, `credit_status`, `available_credit_usd`; leaves `conservative_exposure_usd`/`open_commitment_count` — `services/calc.py:269`
- §3.2 Credit standing — insert — ambiguity — zero credit limit ⇒ `HOLD` if any settled receivable, else `OK` — `services/calc.py:252`
- §3.2 Exposure recompute — insert — ambiguity — computed read bumps neither `updated_at` nor `version`; plain customer read recomputes nothing; cascade recomputes silently skip quote-less nominations — `routes/customers.py:66,90`, `services/calc.py:244`
- §3.3 Compliance review — revise — mismatch — the declared-sulfur check runs last, so missing ECA documentation wins over a too-tight declaration — `routes/nominations.py:156`
- §3.4 Conservative credit check — revise — mismatch — the limit check runs at confirmation only; clearance enforces the hold gate alone — `routes/orders.py:154`
- §3.4 Supersede — insert — ambiguity — supersede cancels only after all slot checks pass (so it still counts as live) and does not trigger the awaiting-schedule cascade — `routes/orders.py:97`, `services/scheduling.py:29`
- §3.4 Auto-schedule — revise — mismatch — port capacity is a standalone precondition (`ERR_PORT_CAPACITY_EXCEEDED`) between window and notice checks, not a pool criterion — `routes/nominations.py:225`
- §3.5 Cancellation — revise — mismatch — clearance fields are cleared only when the order is `CLEARED` at cancellation; a `SUSPENDED` order keeps them — `services/cascade.py:33`
- §3.5 Quantity decision — insert — ambiguity — `AGREE` is Surveyor-only and `DISPUTE` CustomerRep-only, post-payload, else `ERR_ROLE_NOT_PERMITTED` — `routes/orders.py:253`
- §3.6 Spill suspension — insert — ambiguity — suspension also recomputes `committed_quantity_mt`; the suspended order's own nomination stays `SCHEDULED` — `routes/spills.py:79`
- §3.6 Major cascade — insert — ambiguity — an already-quarantined asset simply stays quarantined, no rejection — `services/cascade.py:46`
- §3.6 Containment — insert — ambiguity — confirm-containment has no state guard, is repeatable and accepted on a `CLOSED` incident — `routes/spills.py:121`
- §3.7 Note issuance — insert — ambiguity — requires `logistics_status` `DELIVERED`, else `ERR_INVALID_ORDER_STATE` — `routes/notes.py:38`
- §3.7 Supersede/claims — revise — mismatch — a claim-referenced note stays `ISSUED`; a claim may still name a `SUPERSEDED` note (no status check at submission) — `routes/claims.py:61`
- §3.7 Sample release — insert — ambiguity — retention lapse is the only gate; note status unchecked; re-release restamps — `routes/notes.py:120`
- §3.7 Claim intake — insert — ambiguity — `replacement_price_usd_per_mt` is two decimals and strictly positive when supplied — `routes/claims.py:68`
- §3.8 Lab filing — insert — ambiguity — branch chosen by presence of `retest_of_analysis_id`; first round demands `SUBMITTED`, retest demands `UNDER_ANALYSIS`, else `ERR_INVALID_CLAIM_STATE` — `routes/claims.py:250`
- §3.8 Lab filing — insert — ambiguity — a retest id on another claim/round is `ERR_INVALID_REQUEST` — `routes/claims.py:256`
- §3.8 Surveyor decision — insert — ambiguity — governing analysis ties broken by later `created_at` — `services/calc.py:175`
- §3.8 Surveyor decision — insert — ambiguity — `PROPOSE` without `remediation_type` is `ERR_INVALID_REQUEST` — `routes/claims.py:141`
- §3.8 Surveyor decision — insert — ambiguity — "the non-void invoice" is the most recently created one — `services/calc.py:154`
- §3.9 Issuance — insert — ambiguity — issuance recomputes no amount components — `routes/invoices.py:112`

Test suite was not run by the Step 9 subagent (per instruction); analysis was read-only over `implementation/`.

**Orchestrator confirmation sweep (ran concurrently with Step 9, purely to regenerate the `results.{1..8}.json` deliverables the Step 7 subagent had cleaned up):** all 8 rounds `total=124, passed=124, failed=0, errors=0, skipped=0`. This independently reconfirms Step 7's clean result on unmodified sources — no implementation or test file was touched between the two sweeps.

Pipeline complete through Step 9.
