# Worklog — task_2214_dental_support_organization_practice_integration

## Step 1: Create task directory — 2026-09-01T02:15:32.732Z

Created `tasks/task_2214_dental_support_organization_practice_integration/` and `tasks/task_2214_dental_support_organization_practice_integration/workspace/`.

## Step 2: Generate scaffold artifacts — 2026-09-01

Wrote `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) and
`SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) from the verbatim scenario description, targeting
above-expert difficulty. `scaffold_lint.py` reports `VERDICT: clean lint`
(69 endpoints, 15 entities, 21 §1.8 instances, 73 §1.9 recipes + 22 `excluded_because`
stubs, 1535 calls scanned).

### Step 2 subagent summary (verbatim)

All three scaffold artifacts are complete and the lint is clean.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2214_dental_support_organization_practice_integration/`)
- `SCAFFOLD.yaml` — §1.0–§1.7, 2860 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` (§1.8), 2328 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` (§1.9), 5422 lines
- `worklog.md` — Step 2 entry appended

## Scaffold contents
- **Domain**: `dso-practice-integration`, prefix `/dso`; archetype workflow_orchestration + compliance_audit; layers `cascading_side_effects`, `dual_variant_calculation`, `optimistic_concurrency`, `derived_field_reconciliation`; topology flat, state-machine shape parallel, role model segregation_of_duties, consistency immediate; logical clock pinned at `2026-09-01T00:00:00Z`.
- **15 entities**: Affiliation, ConversionVendor, Practice, Doctor, DoctorEmployment, ServiceAgreement, ServiceLineItem, MigrationBatch, PayerContract, FeeScheduleItem, PayerEnrollment, EarnoutTranche, SupplyPreferenceException, VendorConsolidation, ClinicalQualityReview.
- **11 state machines** (Affiliation, Practice posture, DoctorEmployment with parallel custody/non-compete dimensions, ServiceAgreement, MigrationBatch with a remediation cycle, PayerContract, PayerEnrollment, EarnoutTranche, SupplyPreferenceException, VendorConsolidation, ClinicalQualityReview) + **2 OCC concurrency rules** (`expected_affiliation_version`, `expected_practice_version`).
- **11 calculations**, including the 8-step dual-variant `earnout_payout` (PROVISIONAL annualization vs FINAL lag holdback, with chained fee-tier → growth-multiple lookups), dual-variant `doctor_compensation`, `fee_schedule_blended_impact` (round-at-the-line), `chart_migration_validation`, `clinical_quality_score`, `credentialing_lead_time`, `practice_posture` (5-clause precedence), `credentialing_rollup`, `vendor_consolidation_savings`, and two conservation ledgers.
- **50 ordered validations**, **69 endpoints**, **60-error catalog**, **5 RBAC roles** (DsoDealCounsel, DsoIntegrationLead, DsoFinanceController opaque; ClinicalDirector, Dentist entity-backed on Doctor, with per-tranche segregation of duties via `X-User-ID`).

## Design-file instance counts
- §1.8: **9 rules / 21 instances** (variant_divergence, chained_lookup, non_linear_state_machine, transitive_cascade, validation_priority_pair, boundary_condition, state_dependent_validation, interval_semantics, compensating_invariant — each with ≥2 differentiated instances).
- §1.9: **95 instances across all nine sections** — 73 full `test_recipe`s + 22 `excluded_because` stubs: entities 12, state_machines 18, calculations 14, validations 30, endpoints 5, errors 2, rbac 5, cross_cutting_complexity_layers 7, consistency_model 2.
- Every one of the 60 error codes is triggered by at least one recipe (or covered by a stub naming an existing §1.8 instance); all instance names are unique across both design files; no forbidden concurrency vocabulary.

Notable fixes made during authoring: field names aligned to §1.1 (`validation_error_rate_bps`, `records_quarantined`, `charts_migrated_count`, `annualized_net_collections_cents`, `incremental_cost_cents`, `earnout_reserved_cents`); the FEE_SCHEDULE_EMPTY-vs-ENROLLMENTS_NOT_APPROVED priority recipe was corrected to seed one enrollment so the contract is actually in `PENDING_CREDENTIALING`; and the five sub-resource GET paths were renamed to `{id}` form to satisfy lint check (f).

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(Coverage: 69 endpoints declared, 15 entities declared, 21 §1.8 instances scanned, 73 §1.9 instances scanned, 1535 calls scanned.)

## Step 3: Copy shared files — 2026-09-01T09:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (53 lines).

## Step 4: Generate PRD — 2026-09-01T09:20:00.000Z

PRD generated and audited.

**Output**: `workspace/PRD.md` — 527 lines, ~13,300 words.

**Structure**
- §1 Introduction (3 paragraphs: the "buys practices, not dentistry" framing, the affiliation arc, and why the rules interlock)
- §2 Global Specifications, 12 subsections: 2.1 Actors/Identity Headers/Clinical Authority; 2.2 API Response Structure (pasted verbatim from `section-2.2-response-structure.md`, byte-identical); 2.3 Pagination and List Ordering; 2.4 Common Resource Properties and the Logical Clock; 2.5 Money, Basis Points and Rounding Discipline; 2.6 Integration Posture: The Derived Gate; 2.7 Cascades, Derived Counters and Version Propagation; 2.8 Conserved-Quantity Ledgers; 2.9 Stale-Parent-Version Rejection; 2.10 Resource Addressing and Left-to-Right Path Resolution; 2.11 Request Evaluation Order and Error Precedence (all 50 gates, ordered); 2.12 The Corporate-Practice-of-Dentistry Boundary
- §3 Business Logic, 9 subsections: deal origination → MSA scope → close cascade → the employment row's three dimensions → chart migration → payer/credentialing/fee schedule → vendor consolidation & preference exceptions → clinical quality → earn-out pool
- §4 Endpoint Definitions: 4-column table, all 69 endpoints
- §5 Error Code Catalogue: 2-column table, all 60 error IDs

**Hard Contract results**: field coverage PASS (146/146 entity fields, 87/87 request bodies, 12/12 query params); rule coverage PASS (50/50 validations, 2/2 OCC, 48/48 transitions, 10/10 calculations, 46/46 side-effects, 146/146 field contents, 8/8 sibling-branch symmetry groups); path purity PASS (789 backtick tokens scanned, 0 paths/methods in §3).

**Additional verifications**: §4 table matches the scaffold exactly on all 69 method+path pairs with zero role-list mismatches; §5 matches all 60 error IDs with zero HTTP-status mismatches; §2.11's 50 numbered gates are in the scaffold's exact `priority` order (including the four deliberate cross-family inversions — 29 above 34, 10 above 49, 31 above 37, and the 20/21 ordering on review close); all 25 calculation constants appear with both human units and exact integers; every enum member value across all 15 entities appears in the prose.

**Repairs made during the audit**: added explicit transition arrows for seven transitions that were narrated but not glyph-marked (`PRE_CLOSE`→`STABILIZING`, `STABILIZING`/`RESTRICTED`/`INTEGRATED`→`FROZEN`, the `OFFERED`→`OFFERED` self-transition, `STAGED`/`QUARANTINED`/`HELD`→`SCHEDULED`, `NOT_STARTED`→`SUBMITTED`); named the two OCC write endpoints by path in §2.9; added the missing `ConversionVendor.version` increment on cutover scheduling and the `Practice.version` increment on first enrollment submission.

The two withheld design files were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T10:40:00.000Z

All 13 Stage-2 files are written and both mandatory audits pass. Final state:

## Files written

**Stage 1 — `test_helpers/` (9 modules):** `__init__.py`, `api_client.py` (69 endpoint wrappers), `api_errors.py` (67 error IDs + HTTP map registered with the framework), `assertions.py` (22 domain assertions incl. the two conserved-ledger checks), `constants.py`, `factories.py` (16 payload factories), `fixtures.py` (~886 lines, five tiers of builders), `test_users.py`, `types.py`.

**Stage 2 — `test_suite/` (conftest + 13 files, 122 tests):**
| File | Tests | Source |
|---|---|---|
| `test_01_earnout_lifecycle_depth.py` | 11 | queue A |
| `test_02_rounding_boundary_arithmetic_depth.py` | 9 | queue A |
| `test_03_chart_migration_depth.py` | 11 | queue A |
| `test_04_credentialing_depth.py` | 10 | queue A |
| `test_05_transaction_cascade_depth.py` | 8 | queue A |
| `test_06_entity_contract_breadth.py` | 12 | Corner/entities |
| `test_07_state_machine_breadth.py` | 14 | Corner/state_machines |
| `test_08_calculation_breadth.py` | 6 | Corner/calculations |
| `test_09_validation_guard_breadth.py` | 12 | Corner/validations |
| `test_10_validation_sequence_breadth.py` | 12 | Corner/validations |
| `test_11_endpoint_and_error_breadth.py` | 7 | Corner/endpoints + errors |
| `test_12_role_authorization_breadth.py` | 5 | Corner/rbac |
| `test_13_concurrency_and_consistency_breadth.py` | 5 | Corner/cross_cutting + consistency_model |

## Counts per queue
- **Queue A (difficulty, §1.8):** 21/21 non-stub instances covered by **49 tests**.
- **Queue B (corner, §1.9):** 73/73 real instances covered by **73 tests**, exactly one per instance. The 22 `excluded_because` stubs carry no `test_recipe` and are not test sources.

## Instances skipped
**None.** Every non-stub instance in both indices produced a test. Six recipes contained assertions that contradict the PRD; in each case the instance's actual claim was still PRD-derived, so the PRD-legal value was substituted rather than dropping the instance:
1. `separation_reason: RESIGNATION` → `VOLUNTARY` (PRD §3.4 declares only VOLUNTARY / TERMINATED_FOR_CAUSE / NON_RENEWAL).
2. `non_compete_months: 30` → two 24-month covenants separated a month apart (PRD §3.1 bounds it 0–24 inclusive).
3. `rbac/deal_counsel_cannot_run_integration_lead_exclusive_operations`: SIGNED setup → CLOSED deal.
4. `rbac/dentist_cannot_decide_...`: asserted `incremental_cost_cents == 212160` at REQUESTED → asserted `None` at REQUESTED and `212_160` only after APPROVE.
5. `cross_cutting/stale_affiliation_version_...`: contradictory "no tranches" setup vs `total_count == 2` → project tranche 1 first, then the stale/fresh pair.
6. `cross_cutting/credentialing_rollup_reconciles_...`: asserted the PRD-derived 0 → 1 (after submit) → 0 (after approve) → 0, since PRD §2.7 counts only `SUBMITTED`.

Also corrected one pre-existing brittleness in `test_09`: an exact `created_at == "2026-09-02T00:00:00Z"` comparison → prefix match (PRD §2.4 three-fractional-digits rule).

## Audit results
- **Compile/collect:** `pytest --collect-only` → **122 tests collected**, no import errors.
- **PRD-citation pass:** 231 `PRD §x.y: "…"` quotes across 13 files, **0 missing**.
- **Design-tag pass:** 122 `Design:` lines, exactly one per test, **0 unresolved**, **0 pointing at a stub**; queue A 21/21 and queue B 73/73 covered, no dual tags.
- **Helper audit:** `MISSING=[] UNUSED=[] BAD_API=[]` for all 13 files.
- **Forbidden constructs:** no `pytest.mark.skip` / `skipif` / `xfail`, no mention of "scaffold" anywhere in generated code.

## Step 6: Generate implementation — 2026-09-01T11:20:00.000Z

Implementation complete and smoke-verified.

## Files written

31 files, ~3,930 lines under `workspace/implementation/`:

**Root (11):** `start.sh` (exec-based foreground launcher, guarded `pip install`, `PORT` default 10000, binds `0.0.0.0`), `requirements.txt`, `app.py`, `config.py` (every domain constant/enum verbatim from SCAFFOLD), `errors.py` (all 60 error IDs → HTTP status), `clock.py` (logical clock), `response.py` (envelope + `req_` + 20-char request IDs), `db.py` (in-memory dicts, 15 collections, empty at boot), `middleware.py` (auth/RBAC/entity-backed identity), `payload.py` (payload + pagination gates), `support.py` (transaction wrapper, lookups, posture/OCC guards).

**`routes/` (15):** `affiliations` (7), `conversion_vendors` (2), `practices` (5), `doctors` (2), `employments` (10), `agreements` (8), `batches` (8), `payer_contracts` (6), `payer_enrollments` (5), `earnout` (6), `supply` (3), `consolidations` (3), `quality` (3), `clock_control` (1), plus `__init__.py` exposing `BLUEPRINTS`.

**`services/` (5):** `calc.py` (11 calculations, `Decimal` ROUND_HALF_UP at prec=80), `derive.py` (all derived counters, posture ladder, 15 serializers, derived fingerprints), `uow.py` (unit-of-work reconciliation), `cascade.py` (the two five-hop cascades), `__init__.py`.

**Endpoint count: 69** (matches SCAFFOLD §1.5 exactly, verified via `app.url_map`).

## Notable design decisions
- **Derived-state reconciliation unit of work** — fingerprints the derived surface of all versioned kinds at request start, applies explicit `touch()` where the spec names a row, then auto-bumps exactly once any row whose fingerprint moved. Freeze/release, contract credentialing edge, credentialing rollup and earn-out measurement state are fixed-point recomputes, hence idempotent.
- **All counters derived on read**, never stored, so compensating operations (rollback, claw-back, remediate, re-submit) conserve their ledgers — claw-back returned the pool to exactly 100,000,000 cents.
- **`make-effective` ordering:** §2.11's numeric ladder (affiliation state 9 < agreement state 14 < fee cap 47) governs over §3.2's prose order.
- **Range vs. business-rule split:** declared field ranges are priority-6 400s; caps routed to dedicated errors (`mgmt_fee_bps` at make-effective, `charts_sampled >= 20`) carry no payload-level floor so they surface as 422s.

## Verification
Three smoke suites (~110 assertions) against a booted server exercised every route group: the five-hop affiliation-close and doctor-separation cascades, freeze→SUSPENDED enrollment / HELD batch and the reverse contract edge, OCC 412s, segregation of duties, self-review and corporate-practice refusals, 48-hour cutover buffer vs. vendor capacity, enrollment half-open overlap, both earn-out variants, and all pagination/404/400 shapes. `py_compile` clean; `__pycache__` removed. No test_suite/test_helpers/DESIGN files were read.

## Step 7: Test-fix iteration loop — 2026-09-01T11:45:00.000Z

All green. Final state: **8/8 parallel rounds at 122/122**.

## Summary

**Iterations run:** 3 full 8-round parallel sweeps (round 1: 106/122 × 8, round 2: 121/122 × 8, round 3: 122/122 × 8). Failures were fully deterministic — identical 16-test failure set in all 8 rounds of sweep 1, identical single failure in all 8 rounds of sweep 2. No flakiness surfaced.

**Tests deleted:** none. Two assertions were removed/corrected under STEP 1c partial-coverage handling (details below); no whole test failed STEP 1a or 1b.

**Fixes applied to `test_helpers/`:** none. Fixtures, factories and role headers all traced correctly to PRD's role-to-resource model.

**Fixes applied to `test_suite/`:**
- `test_suite/test_10_validation_sequence_breadth.py::test_the_version_guard_answers_before_the_posture_gate` — removed the second assertion (`POST /dso/migration-batches` with a *matching* `expected_practice_version` at a non-affiliated practice must return `ERR_PRACTICE_NOT_AFFILIATED`). PRD §2.11 position 17 enumerates the six operations that gate on `affiliation_status == AFFILIATED` ("scheduling a cutover, activating a fee schedule, submitting an enrollment, finalizing a consolidation, standardizing staffing and harmonizing compensation") and batch staging is not among them; §3.5's staging paragraph names only the `expected_practice_version` guard. Scaffold rule that drove it: `Corner/validations/stale_practice_version_preempts_the_not_affiliated_gate` — scaffold-only gate, PRD-silent. The covered half (stale version → `ERR_STALE_PRACTICE_VERSION` 412, no state written, zero batches listed) is retained.
- `test_suite/test_05_transaction_cascade_depth.py::test_only_the_activated_doctor_gains_an_enrollment_and_the_contract_moves` — corrected `pending_credentialing_count` from `1` to `0`. PRD §2.7 verbatim: "`pending_credentialing_count` counts the enrollments reachable from that practice whose status is `SUBMITTED`", and PRD §3.3 hop four verbatim: "Each created enrollment opens in `NOT_STARTED`". A cascade-created enrollment therefore cannot be counted; the implementation was right. (`enrollment_open_count == 1` still asserted, since §2.7 counts `NOT_STARTED` **or** `SUBMITTED` for that one.)

**Fixes applied to `implementation/`:**
- `workspace/implementation/clock.py` — added `to_iso_instant()`, rendering business instants as whole-second ISO 8601 UTC (`2026-09-01T00:00:00Z`), falling back to three fractional digits only for genuinely sub-second values. PRD §2.4 mandates three fractional digits for `created_at` (and §2.2 for `api_request_timestamp`) but not for the clock-stamped business instants, which the PRD itself writes as `2026-08-01T00:00:00Z` / `9999-12-31T00:00:00Z`; the old code applied the `created_at` formatter to every date-time, including echoing back client-supplied `cutover_start_at` / `dso_schedule_effective_date` in a different string than was stored.
- `workspace/implementation/services/derive.py` — switched the 16 business date-time serializations (`diligence_opened_at`, `signed_date`, `close_date`, `comp_effective_date`, `separation_date`, `non_compete_end_date`, `effective_date`, `term_date`, `submitted_at`, `decided_at`, `cutover_start_at`, `cutover_end_at`, `dso_schedule_effective_date`, `measurement_start`, `measurement_end`) to `to_iso_instant`; `created_at`/`updated_at`/`api_request_timestamp` still use the three-fractional-digit form §2.2/§2.4 require. This single change resolved 15 of the 16 sweep-1 failures.

Storage remains in-memory Python dicts with nothing seeded; no endpoint, field, or side effect was added, and no PRD-required check was removed or weakened. Sweep result files were cleaned up.

## Step 7 verification sweep (orchestrator) — 2026-09-01T11:55:00.000Z

Independent 8-round parallel sweep re-run by the orchestrator: `results.1..8.json` all report `122 / 122`.

## Step 8: Finalize PRD — 2026-09-01T12:00:00.000Z

Done. `PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 527 lines
- `PRD_FINALIZED.md`: 529 lines (+2 lines, **+0.38%**) — one new paragraph plus its blank separator; no existing line altered.

## Changes
- **§2.4 (Common Resource Properties and the Logical Clock)** — *insert* — pins the serialization format of the 16 business date-time fields: whole-second ISO 8601 UTC (`…T00:00:00Z`) with no fractional digits, falling back to three fractional digits only for genuinely sub-second instants; restates that the three-fractional-digit form stays mandatory for `api_request_timestamp`, `created_at` and `updated_at`. — `implementation/clock.py:68-92` (`to_iso_instant`), `implementation/services/derive.py:298-300, 373-376, 393, 421-422, 436-438, 467-470, 484-485`, `derive.py:273-275` and `response.py:20` (the three-digit paths).

## Step 7 items that needed **no** PRD edit
- `test_10_validation_sequence_breadth.py` (removed the "matching version at non-affiliated practice → `ERR_PRACTICE_NOT_AFFILIATED`" assertion): PRD already determines this. §2.11 position 17 enumerates exactly six gated operations and batch staging is not among them; §3.5's staging paragraph names only the `expected_practice_version` guard. Confirmed against `implementation/routes/batches.py:32-66`. Prose kept verbatim.
- `test_05_transaction_cascade_depth.py` (`pending_credentialing_count` 1 → 0): PRD §2.7 and §3.3 hop four already pin this verbatim; `derive.py:154-159` matches. Pure test bug. Prose kept verbatim.

## Per-edit pre-edit search log

**Edit 1 — §2.4 business date-time serialization**
- **(a) Subject:** how the server renders date-time values in JSON responses, and which fields are affected.
- **(b) Impl paths enumerated:** `grep -rn "to_iso\|isoformat\|strftime" --include=*.py .` over the whole implementation — complete rendering callsite set is `response.py:20`, `derive.py:273/275`, `derive.py:406`, `derive.py:456`, plus 16 `to_iso_instant` callsites. `clock.py:50-92` (both formatters; `to_iso_instant` delegates to `to_iso` when `microsecond` non-zero, returns non-`datetime` input unchanged). Walked every serializer in `derive.py:281-559` field-by-field to confirm the 16-field inventory is exhaustive (affiliation 3, doctor_employment 3, service_agreement 1, migration_batch 2, payer_contract 1, payer_enrollment 4, earnout_tranche 2); `practice`, `doctor`, `supply_preference_exception`, `vendor_consolidation`, `clinical_quality_review`, `service_line_item`, `fee_schedule_item` carry no business instants. `routes/clock_control.py` returns `{}`, unaffected. `routes/payer_enrollments.py:26,40-71` — omitted `term_date` stored as `None`; `clock.OPEN_ENDED` used only for comparison, never persisted. `clock.py:101-111` (`add_months`) — `non_compete_end_date` inherits `separation_date`'s sub-second component.
- **(c) Wording adjustments:** (1) framed the rule as *rendering*, not *clock-stamping*, since several fields are client-supplied or computed; the pre-existing §2.4 clock-stamp sentence left untouched. (2) Dropped a draft claiming client values are "echoed back exactly as stored" — `parse_iso` normalizes `+00:00` offsets and `.000` fractions — replaced with "echoed back … in the whole-second form". (3) Qualified the fallback as "a genuine sub-second component", matching the `if value.microsecond` branch. (4) Scoped the mandatory-three-digit clause to "every resource that carries them" so it stays true of the two `id`+`created_at`-only resources.

## Step 9: Complete PRD — 2026-09-01T12:15:00.000Z

Done. All 28 planned edits applied to `workspace/PRD_COMPLETED.md`.

## Size
| File | Lines | Chars |
|---|---|---|
| `workspace/PRD_FINALIZED.md` (source) | 529 | 101,264 |
| `workspace/PRD_COMPLETED.md` | 529 | 106,151 |

Char delta: **+4,887**. Line count unchanged — every change is an in-paragraph insert or revision; no new paragraphs, no new sections, no new table rows.

## Counts
- **19 ambiguity-pins**
- **9 mismatch-revisions**
- **28 total**

## Changes
- §2.1 — revise — mismatch — struck the claim that ownership checks compare a resource's doctor foreign key to `X-User-ID`; clinician identity feeds only the §2.12 licensure and self-review checks, no ownership precondition exists anywhere, so any resolving dentist may act on any employment row — `middleware.py:23-38`, `routes/quality.py:114`
- §2.3 — insert — ambiguity — equal `created_at` values are broken by creation sequence, earliest inserted first — `db.py:73-75`
- §2.3 — revise — ambiguity — only employment supply-preference-exceptions and clinical-quality-reviews accept a `status` filter; practice consolidations, agreement line items and contract fee-schedule items are pagination-only; all five paginate; an unmatched filter value yields an empty page with `total_count` zero — `routes/employments.py:254,269`, `practices.py:100`, `agreements.py:119`, `payer_contracts.py:105`, `support.py:114-117`
- §2.4 — insert — ambiguity — a freshly created row carries `version` 1 and an `updated_at` equal to its `created_at` — `db.py:49-60`
- §2.7 — insert — ambiguity — enumerated exactly which rows are re-versioned when their derived surface moves (vendor `active_window_count`; contract `enrollment_open_count`/`fee_schedule_item_count`/`blended_impact_cents`; agreement `line_item_count`; employment credentialing rollup; practice counters and posture; affiliation `practice_count` and pool buckets), each at most one step per request — `services/uow.py:40-55,133-157`, `derive.py:602-635`
- §2.10 — insert — ambiguity — body foreign keys resolve in endpoint declaration order (affiliation before vendor, practice before doctor, contract before employment), and an unknown FK's 404 outranks an absent sibling field's `ERR_INVALID_REQUEST` — `routes/practices.py:21-24`, `employments.py:27-30`, `payer_enrollments.py:35-38`
- §2.11 item 16 — insert — ambiguity — named the exactly three single-decision workflows guarded at position 16 and their opening states — `routes/supply.py:86`, `consolidations.py:62`, `quality.py:101`
- §3.1 — insert — ambiguity — `post_close_doctor_term_months` must be zero or more — `routes/affiliations.py:40-46`
- §3.2 — insert — ambiguity — `finding_count` is mandatory and must be zero or more — `routes/agreements.py:147`
- §3.2 — revise — mismatch — make-effective checks the affiliation gate (position 9) before the agreement gate (position 14), then the fee cap — `routes/agreements.py:162-175`
- §3.4 — revise — ambiguity — the accept-offer consent-only branch applies to every affiliation status other than `CLOSED`, including `DRAFT` and `DILIGENCE` — `routes/employments.py:137-143`
- §3.4 — insert — ambiguity — each `monthly_collections_cents` entry must be zero or more — `routes/employments.py:153-155`
- §3.4 — insert — ambiguity — the compensation cap is compared exactly by cross-multiplication with no rounding, so a zero legacy figure admits only a zero harmonized package — `services/calc.py:112-122`
- §3.4 — insert — ambiguity — `non_compete_end_date` is calendar-month addition with end-of-month clamping, and zero months lands on `separation_date` itself — `clock.py:105-111`
- §3.5 — revise — mismatch — validate-batch order is batch status, then posture, then cutover-window-started; there is no separate affiliation-status gate — `routes/batches.py:165-174`
- §3.6 — insert — ambiguity — pricing a contract already `DSO_SCHEDULE_ACTIVE` is refused with `ERR_INVALID_CONTRACT_STATE` — `routes/payer_contracts.py:71-75`
- §3.6 — revise — mismatch — submit-enrollment order is employment `ACTIVE` (11), enrollment status (13), practice `AFFILIATED` (17), posture (18) — `routes/payer_enrollments.py:110-128`
- §3.6 — insert — ambiguity — resubmitting after denial lifts the contract's `enrollment_open_count` off zero, bumping the contract's `version` and re-firing `LEGACY → PENDING_CREDENTIALING` — `services/uow.py:99-107`, `derive.py:228-233`
- §3.6 — revise — ambiguity — an `APPROVE` decision increments the `version` of the enrollment, the practice and the contract — `routes/payer_enrollments.py:152-158`, `uow.py:133-157`
- §3.6 — insert — ambiguity — an omitted `erosion_override_ack` is read as false — `routes/payer_contracts.py:116`
- §3.7 — revise — mismatch — the requested `doctor_employment_id` is never compared to the requesting dentist's own doctor identity, so it need not be that dentist's own employment — `routes/supply.py:19-33`
- §3.7 — revise — mismatch — decide-exception checks employment `ACTIVE` before exception `REQUESTED`, and a non-`REQUESTED` exception is refused with `ERR_INVALID_WORKFLOW_STATE` — `routes/supply.py:80-90`
- §3.7 — insert — ambiguity — finalizing a non-`PLANNED` consolidation is refused with `ERR_INVALID_WORKFLOW_STATE`, checked before the affiliated and posture gates — `routes/consolidations.py:62-69`
- §3.9 — revise — mismatch — reserve checks the affiliation and measurement state before the tranche state, per §2.11 — `routes/earnout.py:127-136`
- §3.9 — insert — ambiguity — settle carries no affiliation-status or `earnout_measurement_state` gate, so a reserved tranche settles even while the deal's measurement window is `SUSPENDED` — `routes/earnout.py:173-187`
- §3.9 — insert — ambiguity — a successful reservation also stamps `lag_holdback_cents` as zero — `routes/earnout.py:31-37`, `calc.py:57-61`
- §3.9 — revise — mismatch — claw-back checks the affiliation `CLOSED` gate before the tranche `SETTLED` gate — `routes/earnout.py:221-227`
- §4 — insert — ambiguity — the logical-clock capability is the sole modifying operation returning no resource; its envelope `data` is an empty object — `routes/clock_control.py:27`

## Deliberate non-change
The framework-level `ERR_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED` and `ERR_INTERNAL` handlers in `implementation/app.py` are not in the §5 catalogue. Pinning them would have required new error-table rows, which the "change as little as possible / never add new sections" constraint forbids; they are unreachable from any documented request shape.

---

**PIPELINE COMPLETE** — Steps 1–9 all finished. Final test state: 8/8 parallel rounds, 122/122 tests passing.
