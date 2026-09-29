## Step 1: Create task directory — 2026-09-04T16:55:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2756_transfer_of_development_rights_program and its workspace/ subdirectory. Index 2756 was pre-assigned by the orchestrating command; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-04T18:38:00.000Z

Scaffold for task 2756 is complete and lint-clean.

## Files written

| File | Lines | Content |
|---|---|---|
`SCAFFOLD.yaml` | 3314 | §1.0–§1.7 only (no design keys) |
`SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1812 | single key `scaffold_difficulty_design` — 9 `rule_id`s × 2–3 = 19 instances |
`SCAFFOLD_CORNER_DESIGN.yaml` | 3867 | single key `scaffold_corner_design` — 9 sections, 77 instances (54 recipes + 23 `excluded_because` stubs) |

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  869

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Scaffold shape

`api_prefix: /tdr`, `difficulty_level: expert_plus`, `entity_topology: graph`, `state_machine_shape: cyclic`, `consistency_model: immediate`, `role_model: segregation_of_duties`, layers = dual_variant_calculation / cascading_side_effects / optimistic_concurrency / rate_threshold_triggers / derived_field_reconciliation.

14 entities · 9 state machines · 3 OCC rules · 12 calculations · 48 numbered validations · 60 errors · 59 endpoints · 6 roles.

Corner sections: entities 11, state_machines 12, calculations 7, validations 9, endpoints 6, errors 20, rbac 4, cross_cutting 7, consistency_model 1.

## Verified invariants (scripted checks, not eyeballed)

- All 60 §1.6 error ids are triggered somewhere across the two design files (0 uncovered).
- All 59 §1.5 endpoints are exercised; the 17 that appear only in assertion prose rather than as structured calls are all pure GET reads, each named in at least one §1.9 retrieval/listing assertion.
- Instance names unique across the union of both design files; all 23 stub `difficulty_instance` references resolve to real §1.8 instance names; every recipe has `setup` / `setup_api_calls` / `trigger` / `assert` and every call carries `call` + `payload` + `as`.
- The directive line "harder than expert level" is absent from SCAFFOLD.yaml.

## Design decisions worth recording

- **Role-denial triggers can't be structured calls.** Lint requires `as:` ∈ the endpoint's declared roles, so RBAC refusals (Developer screening, Landowner certifying) are pinned as assertions against a legal baseline call. The refusals that *are* expressible — `ERR_CHANNEL_ROLE_MISMATCH` (priority 9) and `ERR_NOT_RESOURCE_OWNER` (priority 6) — carry the RBAC section's structured coverage.
- **Two errors looked unreachable and needed setup tricks.** `ERR_EASEMENT_NONCOMPLIANT` is normally masked by the BACKING_DEFICIENT cascade, so its recipe over-collateralizes (3 units from two easements against required 2) to keep the application DESIGN_APPROVED after one freeze; `ERR_BACKING_INSUFFICIENT` finalizes a fresh DESIGN_APPROVED application with zero redemptions, since the cascade only fires on release/freeze events.
- **One §1.8 assertion was wrong and got fixed:** a double reversal reports `ERR_TRANSACTION_NOT_SETTLED` (priority 19), not `ERR_REVERSAL_NOT_PERMITTED` (priority 42). That freed priority 42 for a §1.9 retire-then-reverse recipe.
- **One §1.1 self-inconsistency was fixed:** `ReceivingSiteApplication.allocated_bonus_units` was `default: null` while the intake side-effect said it starts at 0; now `default: 0`.
- **Priority-ordering demos in §1.9 are disjoint from §1.8's pairs:** 6 before 23 (ownership before stale version), 23 before 45 (stale before insufficient funds), 32 before 42, 47 before 46, 8 before 21, 25 before 40, 2 before 14.
- **`Party.version` is bumped only by `POST /tdr/parties/{id}/account-actions`** — settlements and holdings recomputes deliberately leave it alone, which is what makes the OCC recipe's "a rejected debit does not consume the version" assertion meaningful.

Orchestrator verification: all three files present and non-empty; grep for the difficulty directive in SCAFFOLD.yaml returns nothing (no leak).

## Step 3: Copy shared files — 2026-09-04T18:38:30.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T18:56:00.000Z

PRD generation is complete.

## Output
`workspace/PRD.md` — **508 lines**, written in seven sequential `cat >> PRD.md` heredoc appends plus two table appends (no single giant write; no truncation).

## Sections written
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Program Actors and RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Registry Record Properties · 2.5 The Logical Clock · 2.6 Units, Cents, Basis Points and Rounding · 2.7 Cascading Consistency Across the Register · 2.8 Stale-Version Rejection on Registry Writes · 2.9 Path Resolution · 2.10 Order of Evaluation (all 48 rungs, ascending) · 2.11 The Two Conservation Invariants
- `## 3. Business Logic & Workflows` — 3.1 Parties/Municipal Bank/account standing · 3.2 Sending & receiving area designation · 3.3 Parcel enrollment and baseline allocation · 3.4 Severance review and allocation grant · 3.5 Certification, easement recording, certificate issuance · 3.6 Registry: chain of title, splits, retirement · 3.7 Valuation and the market (appraisal schedules, proposal, pricing, settlement, cancellation, reversal) · 3.8 Receiving-site entitlement (design review, backing, absorption) · 3.9 Easement stewardship, compliance cascade, program evaluation
- `## 4. Endpoint Definitions` — intro paragraph + 4-column table, **59 endpoints**
- `## 5. Error Code Catalogue` — 2-column table, **60 error identifiers**

## Coverage
- **Entities:** all 13 (`Party`, `SendingArea`, `ReceivingArea`, `AppraisalSchedule`, `SendingParcel`, `SeveranceApplication`, `ConservationEasement`, `Certificate`, `CertificateTransfer`, `MarketTransaction`, `ReceivingSiteApplication`, `CertificateRedemption`, `MonitoringInspection`, `ProgramEvaluation`).
- **State machines:** all 59 transitions across 9 machines, including both parallel dimensions on `ConservationEasement` (`recording_status` / `compliance_status`) and `Certificate` (`lifecycle_status` / `market_status`), the three cycles (severance revision, design review, backing deficiency), and the 4-link freeze cascade plus its 4-link compensating cascade.
- **Calculations:** all 11, with every constant and rounding discipline in prose (soil multipliers, double-flooring in bonus sizing, the two bank basis-point adjustments, the 350/275/200-bp fee tiers off gross, the 150/75/0-bp equity surcharge, the 3000-bp band, the 0.5/0.3/0.2 severity weights with 30/60/90-day cure bands, and both `equity_index` variants).
- **Concurrency:** all three OCC rules and `ERR_STALE_PARENT_VERSION` (412).

## Hard Contract verification (machine-checked)
- **Contract 1 — Field-Name Coverage: PASS.** 167 distinct identifiers from `entities[].fields[].name` plus every endpoint `input` / query / path param; **0 missing** from backticked PRD prose.
- **Contract 2 — Rule Coverage: PASS.** All 48 validation error identifiers appear in §1–§3 prose (not only in the §5 table); all enum values across all entities appear in prose (0 missing); all 59 transitions covered (some via prose phrasing rather than literal arrows, e.g. "moves to `CURED` from whichever of `VIOLATION_NOTICED`, `UNDER_CURE`, or `ESCALATED` it currently occupies"); both `applies_to` scoping and sibling-branch symmetry (administrator-close vs system-close of a sending area; PROVISIONAL vs FINAL bonus sizing; two `equity_index` variants) are stated explicitly.
- **Contract 3 — §3 Path Purity: PASS.** 1218 backtick tokens in §3; **0 violations**.
- **§2.2 fixed block: byte-identical** to the doc-generator's section-2.2 source.
- **Hygiene:** no difficulty meta-commentary, no "scaffold"/"test_recipe" references, no fuzzy quantifiers, no operator syntax, no pseudocode.

## Scaffold contradictions adjudicated (worth flagging to the test-suite author)
1. `SeveranceApplication.allocated_units` / `residual_units_retained`: entity default `null` vs endpoint side_effect "start at 0" → PRD says **start at 0**.
2. Validation priorities 46/47: strict ascending order would make `ERR_SENDING_CAP_EXHAUSTED` unreachable → made mutually exclusive in prose (exhausted capacity → 47; capacity remaining but three-way minimum below one → 46).
3. Settle authorization: endpoint table lists `[ProgramAdministrator]` only, state machine names the counterparties → **endpoint table governs** (administrator-only settlement).
4. `REVERSAL` chain-of-title `price_cents`: state machine says `gross_price_cents`, endpoint says negated → PRD uses **negated**.
5. `conveyance_mode` is in the proposal input list but computed on the entity → PRD states the supplied value is non-authoritative and the stored value is pinned at settlement.
6. Reversal's `PARTIAL` branch is unreachable (reversal requires `WHOLE`) → stated as the `WHOLE` requirement plus the `ERR_REVERSAL_NOT_PERMITTED` rejection.

Orchestrator verification (truncation guard): `wc -l` = 508; all five `## ` headings present; tail is the final row of the §5 error table — a real section boundary, not mid-sentence. No difficulty-directive leak (grep for "expert level"/"harder than expert"/"scaffold" in PRD.md returns nothing).

## Step 6: Generate implementation — 2026-09-04T19:22:00.000Z

(Steps 5 and 6 were launched concurrently in a single orchestrator message, per the skill; Step 6 returned first, so its entry is recorded ahead of Step 5's.)

Implementation complete and verified.

## Deliverable

`workspace/implementation/` — Python 3 + Flask, 3390 lines across 20 source files, in-memory dicts only, store empty on every boot (no seeding anywhere; `core.py:49` documents the invariant).

| file | lines | role |
|---|---|---|
| `start.sh` (executable) | 8 | guarded `pip install` (`if ! python3 -c "import flask"`) then `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 77 | `create_app()`, 8 blueprints, global RLock per request, ApiError/HTTPException/Exception handlers, `application.run(host="0.0.0.0", port=int(os.environ["PORT"] or 10000), threaded=True)` |
| `core.py` | 193 | `Store` (14 empty collections + logical clock defaulting to exactly `2026-08-01T00:00:00Z`), envelope helpers, `req_...` ids, 3-digit-ms timestamps, `touch()` (one version bump per entity per request), Decimal helpers |
| `errors.py` | 83 | all 60 catalogued error ids -> HTTP status |
| `middleware.py` | 61 | `X-User-ID`/`X-User-Role`, 6 roles, ownership (entity-backed roles only), suspension gate |
| `validators.py` | 216 | body/field/enum/cents/decimal-places/datetime parsing, pagination, typed query filters |
| `serializers.py` / `listing.py` | 285 / 27 | explicit projections for 14 entities (transfers carry no `updated_at`/`version`), paging + filter match |
| `services/calc.py` | 263 | both allocation formula variants, restriction extent, tier factor, bonus sizing (two truncations), appraisal-schedule selection, channel pricing, settlement split, deviation bps, severity, cure days, evaluation metrics |
| `services/derive.py` | 277 | reconciled read models, append-only transfer log with per-certificate `seq_no`, freeze/cure/area-close cascades |
| `services/certify.py` | 106 | certification: easement create-or-amend, parcel roll-up, area roll-up, root certificate mint, ISSUANCE row, cap-exhaustion close |
| `routes/*.py` | 1793 | parties, areas + appraisal schedules, parcels + severance, certificates + splits/retire/transfers, market, receiving + redemptions, easements + inspections/cure, ops (clock, sweep, evaluations) |

## Verification

Two smoke suites run against a self-launched server on `PORT=18756` (shut down by its own PID, `2163133`; no pattern kill used):

- Suite 1 (~60 assertions): every PRD worked example, full certify -> market -> redeem -> finalize -> inspect -> cure -> evaluate lifecycle, envelope shape, pagination, RBAC, 404s. **0 failures.**
- Suite 2 (42 assertions): V2 formula variant, easement amendment, cap exhaustion + close cascade, all three market channels, PARTIAL child mint, reversal legs/rows/window boundary at exactly day 30, price band, channel/role and party-kind mismatch, 89-vs-90-day inspection window, severity scoring (23.21 hand-checked), strict sweep comparison, cure from `ESCALATED`. **0 failures.** No tracebacks in the server log.

Three "failures" in suite 2's first run and one crash were all wrong expectations in the throwaway script, not implementation defects: the parcels involved sit in a `V2_GROSS_DISCOUNTED` area (`base_rate 0.25`, `gdf 0.80`), so baseline 23 -> restricted `100*10/23 = 43.48`, baseline `floor(100*0.80*0.25*0.75) = 15`, residual `15-7 = 8`. And PRD §3.7 line 311 blocks reversal only on `units_redeemed`/`units_encumbered`/`units_retired` plus `PARTIAL` mode — a certificate merely split since settlement is still reversible, so the implementation is faithful and the assertion was over-strict.

## PRD ambiguities resolved (PRD prose won over SCAFFOLD)

`ProgramEvaluation.outstanding_units` = issued - redeemed - retired; reversal `price_cents` = negation of gross; proposal `conveyance_mode` accepted but stored null until settlement pins it; severance `allocated_units`/`residual_units_retained` open at 0; `PARTIAL` conveyances never reversible. Judgement calls where the spec was silent: second `MUNICIPAL_BANK` -> `ERR_INVALID_REQUEST` 400; closing a non-`ACTIVE` sending area -> `ERR_SENDING_AREA_NOT_ACTIVE`; seller != holder at proposal -> `ERR_NOT_RESOURCE_OWNER`; non-`HELD` market status on retire/split/redeem (after the frozen rung) -> `ERR_CERTIFICATE_NOT_TRANSFERABLE`; a settlement's own encumbrance excluded from its availability check; `prior_violation_count` increments on notice and on sweep escalation but not on cure; unknown enum query-filter values -> 400.

## Step 5: Generate unit tests — 2026-09-04T19:44:00.000Z

(Launched concurrently with Step 6; returned second.)

All seven translators finished and the audit passes are clean. Final state:

## Files written (task root, not under `workspace/`)

**test_helpers/ — 2309 lines** (Stage 1, unmodified by any translator; mtimes all pre-date Stage 2)
`__init__.py` 44 · `api_client.py` 285 · `api_errors.py` 134 · `assertions.py` 292 · `constants.py` 87 · `factories.py` 223 · `fixtures.py` 685 · `test_users.py` 78 · `types.py` 481

**test_suite/ — 10 483 lines, 126 tests**
`conftest.py` 57 · `test_01_allocation_and_pricing_variants.py` 755 (14) · `test_02_review_and_stewardship_cycles.py` 512 (5) · `test_03_certification_and_freeze_cascades.py` 460 (6) · `test_04_precedence_and_boundaries.py` 663 (10) · `test_05_cross_entity_gates_and_windows.py` 671 (8) · `test_06_conservation_invariants.py` 510 (5) · `test_07_registry_records.py` 758 (11) · `test_08_lifecycle_transitions.py` 811 (8) · `test_09_program_calculations.py` 694 (5) · `test_10_validation_and_endpoint_behavior.py` 1101 (9) · `test_11_error_catalogue.py` 1783 (29) · `test_12_authority_and_concurrency.py` 1708 (16)

## Coverage against the two design indices

- **Queue A (difficulty)**: 19/19 instances translated, 0 skipped, every instance carries >=2 tests (48 tests total).
- **Queue B (corner)**: 53/54 non-stub instances translated (78 tests). All 23 `excluded_because:` stubs produced zero tests, as required.
- **One skip**: `Corner/validations/a_developer_party_cannot_occupy_the_landowner_applicant_slot` — a `DEVELOPER` party can never be a parcel's `owner_party_id` (enrollment enforces `LANDOWNER`), so the scenario necessarily violates the ownership clause and the kind clause at once, and §3's sentence bundles owner-match with kind under one `ERR_NOT_RESOURCE_OWNER` while §2.10 rung 6/7 splits them — the winning error is not PRD-determined.

## Verification performed

- Full-suite `pytest --collect-only`: **126 tests collected, 0 errors**.
- Tag audit: 126/126 tests carry exactly one `Design:` line; 0 untagged, 0 dual-tagged, 0 tags pointing at a non-existent or stub instance.
- Citation audit: **507 docstring quotations, all verbatim** substrings of `workspace/PRD.md` (whitespace-normalised).
- Static audit: no undefined `test_helpers` imports, no unknown `ApiClient` methods, no invalid keyword args to any helper.
- Hygiene: zero `skip`/`skipif`/`xfail`/`pytest.skip`, zero design-file vocabulary, zero `sys.path` hacks or `workspace/` imports, zero money-as-JSON-string literals, no envelope misuse, no duplicate test names, no lowercase module-level mutable state.
- Nothing was written under `workspace/`; `__pycache__` cleaned.

## Adjudicated design-index/PRD contradictions (PRD always won)

1. Design named non-existent PRD fields: `screened_at` (-> asserted `screened_by_user_id`) and `issued_certificate_id` on `SeveranceApplication` (-> asserted `status`/`certified_by_user_id` plus the derived serial).
2. Absolute `version` literals were replaced with relative assertions — unchanged after a refusal, `+1` after an accepted write — since the PRD fixes deltas, not absolute counters.
3. `cure_deadline`: §2.5 lists it as clock-inherited, §3.9 defines it as `inspection_date` + band days; followed §3.9 and compared at date granularity.
4. A design probe used `MUNICIPAL_BANK` as the buyer on an administrator-filed `PRIVATE` deal, which trips party-kind (rung 7) before channel/role (rung 9); switched to a `DEVELOPER` buyer so `ERR_CHANNEL_ROLE_MISMATCH` is unambiguous.
5. Claims the API cannot express were dropped rather than weakened: absence of PUT/PATCH/DELETE on certificate-transfers, a sweep response with `null` data, and list orderings ambiguous when rows share one clock instant.
6. Deliberate under-assertions where PRD is silent: post-release status of an application whose backing was already deficient, `market_status` of a second certificate issued under a standing freeze, and `design_review_round`/`design_reviewed_by_user_id` on the design-review-required branch.

Two notes for the implementation side: account actions are asserted at HTTP 200 (§4's 201 list does not include them), and `test_11` validates setup successes with `get_success_data` (any 2xx) rather than pinning a status the PRD's endpoint table does not document.

Orchestrator verification: `test_helpers/` and `test_suite/` are at the task root (no strays under `workspace/`; `workspace/` holds only INSTRUCTION.md, PRD.md, implementation/).

## Step 7: Run tests and iterate — 2026-09-04T20:04:00.000Z

Clean sweep achieved. Summary:

**Iterations run:** 2

**Tests deleted:** none. The single failure passed both STEP 1a (PRD verbatim coverage) and STEP 1b (unique derivability), and STEP 2 found the test faithful, so it resolved to a genuine implementation defect.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `workspace/implementation/services/certify.py`, easement amendment branch of link one (`else` branch of `easement_of_parcel(...) is None`): deleted the line `easement["severance_application_id"] = app["id"]`. On a second/third certification against a parcel that already has an easement, the implementation was re-pointing the easement at the *current* certifying application. PRD.md line 259 states verbatim: "`recorded_at` is written once at the original recording and is never rewritten by an amendment, and `severance_application_id` likewise continues to name the application that first created the easement." The other amendment effects (`amendment_count` increment, `RECORDED -> AMENDED`, re-minted `recording_reference`, preserved `recorded_at`) were already correct.

**Failure that drove it:** `test_02_review_and_stewardship_cycles.py::TestEasementRecordingAndComplianceDimensionsAdvanceIndependently::test_second_certification_moves_only_the_register_dimension` — failed deterministically in all 8 rounds of iteration 1 with the amended easement naming the second application's id instead of the first's. Not flaky; no load-induced or connection-level failures appeared in either sweep.

**Final sweep, per-round passed/total (from `results.$i.json`):** rounds 1-8 all 126/126.

Storage remained in-memory only; no endpoints, fields, or seeded data were added. `worklog.md` was not read or modified by the subagent.

Orchestrator verification: re-read all 8 `workspace/implementation/results.$i.json` independently — each reports `passed=126, failed=0, total=126, errors=0`, all written at the same sweep instant (19:57). Sweep artifacts are present, so the clean-sweep claim is substantiated.

## Step 8: Finalize PRD — 2026-09-04T20:07:00.000Z

`workspace/PRD_FINALIZED.md` created as a byte-identical copy of `PRD.md`. **Zero edits were warranted.**

## Line counts

| File | Lines | Delta |
| --- | --- | --- |
| `PRD.md` | 508 | — |
| `PRD_FINALIZED.md` | 508 | 0 lines, 0.00% |

(`cmp` reports identical; both md5 `c6767fa18a1de4e282a3c7018dba22d6`.)

## Changes

None. The single Step 7 item was a pure implementation defect corrected *against* a PRD sentence that already states the rule verbatim, so it revealed neither PRD silence nor PRD/impl mismatch.

## Pre-edit search log

Although no edit was committed, the mandatory subject enumeration was run for the one candidate subject before concluding no edit was needed:

**(a) Subject identified** — `ConservationEasement.severance_application_id` (and, adjacently, `recorded_at`) write/rewrite behavior across the easement's whole lifetime, specifically whether an amendment ever re-points either field.

**(b) Impl paths enumerated (read/grepped)**
- `implementation/services/certify.py:10-107` — read in full. Link one create branch writes `severance_application_id: app["id"]` and `recorded_at: now()` at lines 28 and 39; the `else` (amendment) branch, lines 46-52, now touches only `amendment_count`, `recording_status`, `recording_reference`, plus `touch(easement)`. Link two (lines 54-67) rewrites `restricted_acres`, `permitted_residual_units`, `units_issued_total` on the *same* easement object on every certification — neither of the two subject fields is among them.
- Repo-wide greps for `severance_application_id`, `recorded_at`, and `easement_of_parcel` across all `implementation/**/*.py`. Only four `severance_application_id` hits exist: the listing filter (`routes/easements.py:50`), the serializer read (`serializers.py:123`), the single create-branch write (`certify.py:28`), and the explanatory comment (`certify.py:50`). No mutation site anywhere else — not in the freeze/cure cascades, not in the compliance sweep, not in the split/retire paths.
- `recorded_at` hits: `serializers.py:134` (easement read), `serializers.py:179` and `services/derive.py:84` (both `CertificateTransfer`, a different entity), `services/calc.py:207` (evaluation window filter, read-only), and the one create-branch write. Confirms `ConservationEasement.recorded_at` is likewise written exactly once.
- `services/derive.py:23` `easement_of_parcel` — the only lookup feeding the create-vs-amend branch, called from exactly one site, so there is no second amendment path that could diverge.

**(c) Wording adjustment** — none. `PRD.md` line 259 already reads: "`recorded_at` is written once at the original recording and is never rewritten by an amendment, and `severance_application_id` likewise continues to name the application that first created the easement." That is consistent with every enumerated path, including the third-and-later `AMENDED -> AMENDED` repeat that line 259 also covers and that the `else` branch handles unconditionally. Any rewording would have been invented behavior, so the file was left byte-identical.

Orchestrator note: a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 outcome when Step 7's only fix corrected the implementation *against* an already-verbatim PRD sentence. Step 9, by contrast, must not be identical — it runs a full impl scan.

## Step 9: Complete PRD — 2026-09-04T20:40:00.000Z

Orchestrator decision (recorded per the AUTONOMY directive): Step 9 was run as **three sequential passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module**, rather than as a single subagent. A single agent scanning 3390 lines of implementation against a 508-line PRD reliably runs out of working context and returns a file byte-identical to its source (i.e. the scan never happened). Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying and edited in place. Slices: pass 1 = app/core/errors/middleware/validators/serializers/listing + routes/parties, areas, parcels; pass 2 = routes/certificates, routes/market, services/certify; pass 3 = routes/receiving, routes/easements, routes/ops, services/calc, services/derive.

### Aggregate result

`PRD_FINALIZED.md` 508 lines / 114,717 chars -> `PRD_COMPLETED.md` 508 lines / 134,189 chars (**+19,472 chars, +17.0%**; line count unchanged because every edit was an in-paragraph insert or revision — no new sections, no new lines, nothing truncated).

**61 edits total: 46 ambiguity-pins, 15 mismatch-revisions.**

### Pass 1 (core + parties + areas + parcels) — 21 edits: 18 ambiguity-pins, 3 mismatch-revisions

- §2.1 — revise — mismatch — PRD claimed *two* read exceptions (party listing *and* party detail); impl opens party detail to all six roles and restricts only the listing, and applies no ownership filter on any read — `routes/parties.py:61,67`, `middleware.py:47`
- §2.1 — insert — ambiguity — whitespace-only header value counts as empty; role names matched exactly (case-sensitive) — `middleware.py:25-30`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `core.py:161-165`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time — `core.py:169`
- §2.3 — insert — ambiguity — `created_at` ties broken by persistence order (common because of the logical clock) — `core.py:155`
- §2.3 — insert — ambiguity — enum filters reject unrecognised values with `ERR_INVALID_REQUEST`; boolean filter accepts `true/True/TRUE/1` and `false/False/FALSE/0`; string filters accept anything; undeclared query params ignored — `validators.py:184-207`
- §2.7 — insert — ambiguity — `version` advances by exactly one *per request*, not per cascade link, though `updated_at` is refreshed each link — `core.py:137-151`
- §2.10 rung 4 — insert — ambiguity — absent/non-JSON body read as empty object, non-object JSON body rejected; explicit `null` counts as absent; numeric type strictness; timestamp parsing (trailing `Z`/offset normalised, naive read as UTC, bare `YYYY-MM-DD` = midnight UTC) — `validators.py:14-21,24-26,91-109,112-137`
- §2.10 rung 26 — revise — mismatch — rung applies to severance *screening* and to the administrator-driven sending-area close as well — `routes/areas.py:102-103`, `routes/parcels.py:196`
- §3.1 — insert — ambiguity — a second `MUNICIPAL_BANK` registration is `ERR_INVALID_REQUEST` (400), checked after shape validation; `legal_name`/`contact_email` required non-empty and at-sign is the only email check — `routes/parties.py:32-40`
- §3.1 — insert — ambiguity — wrong `amount_cents` combination is caught at rung 4 ahead of the stale-version check; `note` validated but not persisted — `routes/parties.py:78-88`
- §3.2 — insert — ambiguity — area `name` is a required non-empty string with no upper length bound — `routes/areas.py:54,135`
- §3.2 — revise — ambiguity — close accepts a `reason` that is validated but not persisted, and closing a non-`ACTIVE` area yields `ERR_SENDING_AREA_NOT_ACTIVE` (409) rather than being a no-op — `routes/areas.py:101-103`
- §3.2 — insert — ambiguity — each `eligible_sending_area_codes` entry is length-bounded 3-16 like an area `code` — `routes/areas.py:142-143`
- §3.7 (appraisal-schedule paragraph) — insert — ambiguity — supersession targets only `ACTIVE` same-`effective_from` rows and bumps their `version`; those rows are excluded from the overlap test; overlap is evaluated before any supersession is written — `routes/areas.py:212-235`
- §3.4 — insert — ambiguity — `applicant_party_id` != parcel `owner_party_id` is `ERR_NOT_RESOURCE_OWNER`, checked before the `LANDOWNER` kind test; filing `note` not persisted — `routes/parcels.py:119,126-130`
- §3.4 — insert — ambiguity — `screening_note` is stored into `decision_note` (no separate field) and omission leaves it untouched — `routes/parcels.py:189,203-204`
- §3.4 — insert — ambiguity — screening re-checks area-`ACTIVE` before parcel-`FULLY_SEVERED`, so the area error wins when both hold — `routes/parcels.py:196-199`
- §3.4 — insert — ambiguity — supplied `denial_reason` is validated but never stored; all three decision branches store `decision_note` when supplied and leave it untouched when omitted — `routes/parcels.py:216,246,249-250`
- §3.4 — insert — ambiguity — resubmission stores `note` into `decision_note` when given and leaves `allocated_units`, `residual_units_retained`, `applied_formula_version` untouched — `routes/parcels.py:270-276`
- §3.5 — revise — mismatch — the four certification preconditions are evaluated in ladder order, so segregation of duties (rung 8) is checked *before* the `APPROVED` state test; `recording_note` validated but not persisted; response is HTTP 201 — `routes/parcels.py:286-299`

### Pass 2 (certificates + market + certify) — 16 edits: 7 ambiguity-pins, 9 mismatch-revisions

- §2.10 rung 20 — revise — mismatch — retirement carries no rung-24 check, so a `FROZEN` certificate is refused there with `ERR_CERTIFICATE_NOT_TRANSFERABLE` (the blanket "always stopped at rung 24" claim was false for retire) — `routes/certificates.py:131-133`
- §2.10 rung 24 — revise — mismatch — added **settlement** to the `ERR_CERTIFICATE_FROZEN` applies-to list — `routes/market.py:164`
- §2.10 rung 39 — revise — mismatch — added **settlement** to the `ERR_INSUFFICIENT_CERTIFICATE_UNITS` applies-to list — `routes/market.py:169`
- §3.5 Link one — insert — ambiguity — a newly created easement is returned at `version` 1, not 2 (create-and-record is one act, no `touch`) — `services/certify.py:25-45`
- §3.6 chain-of-title — revise — mismatch — `SPLIT_OUT` rows are **not** partyless: both `from_party_id` and `to_party_id` name the parent's holder — `routes/certificates.py:115`, `routes/market.py:189`
- §3.6 Splitting — revise — mismatch — the split's `SPLIT_OUT` row names the holder on both sides (was "no transferor and no transferee") — `routes/certificates.py:115`
- §3.6 Splitting — insert — ambiguity — easement row not rewritten at all; child created at `version` 1; holder's `units_held`/`certificates_held_count` recomputed (Party.version untouched); response is the child at 201 — `routes/certificates.py:114-119`
- §3.6 Retirement — insert — ambiguity — `reason` validated but not persisted; retirement consults neither suspension nor compliance, so `FROZEN` is caught by the `HELD` requirement — `routes/certificates.py:128-133`
- §3.6 Retirement — insert — mismatch — the easement's `units_retired`/`units_outstanding` recompute leaves the easement's own `version`/`updated_at` alone (contra §2.7's blanket cascade rule) — `routes/certificates.py:145`
- §3.7 Proposing — revise — ambiguity — seller-not-holder -> `ERR_NOT_RESOURCE_OWNER` at rung 6 (binds an admin on bank channels too); bank must be the *buyer* on `BANK_PURCHASE` and the *seller* on `BANK_RESALE`; `PRIVATE` constrains neither counterparty's `kind` — `routes/market.py:62-69`
- §3.7 Proposing — insert — ambiguity — `conveyance_mode` is required and enum-validated even though discarded — `routes/market.py:44`
- §3.7 Settling — revise — mismatch — compliance failure is `ERR_CERTIFICATE_FROZEN`; availability = `units_remaining` less encumbrance *other than this transaction's own units*; `market_status` is **not** re-tested (PRD had asserted an `UNDER_CONTRACT` precondition impl never checks); `settlement_note` not persisted — `routes/market.py:156-170`
- §3.7 Settling — insert — ambiguity — with no `MUNICIPAL_BANK` party registered the settlement still completes and fee+surcharge are credited nowhere — `routes/market.py:204-206`
- §3.7 Settling — revise — mismatch — the partial-conveyance `SPLIT_OUT` row names the seller on both sides, and the minted child gets no `ISSUANCE` row (the sale row is its `seq_no` 1) — `routes/market.py:189,199`
- §3.7 Reversing — insert — ambiguity — preconditions evaluate in ladder order (rung 32 window before rung 42), `reversal_reason` must be non-empty, and only the three counters are read so a since-split or onward-conveyed certificate still reverses — `routes/market.py:250-263`
- §3.7 Reversing — revise — mismatch — the conveyed certificate returns to `HELD` **unless** it is `FROZEN`, in which case only the holder changes — `routes/market.py:284-285`

### Pass 3 (receiving + easements + ops + calc + derive) — 24 edits: 21 ambiguity-pins, 3 mismatch-revisions

- §2.5 The Logical Clock — insert — ambiguity — `current_utc` is required; no monotonicity (clock may move backward); setting it rewrites no row; answers HTTP 200 with an empty `data` object — `routes/ops.py:19-25`
- §3.8 intake — insert — ambiguity — required fields, `site_acres` > 0 / <=2dp / no upper bound, `requested_bonus_units` integer >= 1, FK resolution order developer->area, `ERR_PARTY_KIND_MISMATCH` for a non-DEVELOPER — `routes/receiving.py:72-89`
- §3.8 sizing — insert — ambiguity — all four sizing figures (`base_units`, `max_bonus_units`, `required_backing_units`, `provisional_bonus_units`) persist as integers and appear on the detail read — `routes/receiving.py:46-54`, `services/calc.py:64-75`
- §3.8 design DENY — revise — ambiguity — release moves units *out of* `units_encumbered`/`reserved_units`; `released_at` from the clock; redemption and certificate versions increment but the **receiving area's version does not** on this path; `review_note` discarded on non-denial branches — `routes/receiving.py:56-66,152-159`
- §3.8 design resubmission — insert — ambiguity — ceiling compared against the *stored* `max_bonus_units`; revision-limit test precedes the ceiling test; all four sizing figures recomputed; `revision_note` not persisted; `design_reviewed_by_user_id` not cleared; backing figures untouched — `routes/receiving.py:163-186`
- §3.8 allocation preconditions — insert — ambiguity — `units` >= 1, sole FK is `certificate_id`, non-terminal means not `FINALIZED`/`DENIED`; the residual `market_status`-must-be-`HELD` guard is described as unreachable behind rung 20 — `routes/receiving.py:263-289`
- §3.8 allocation effects — insert — ambiguity — `confirmed_at`/`released_at` open unset; certificate and area versions increment — `routes/receiving.py:306-323`
- §3.8 release — insert — ambiguity — `reason` not persisted; `RELEASED` with `released_at`; redemption/certificate/area/application versions all increment; no certificate-state or suspension check — `routes/receiving.py:352-377`
- §3.8 finalization gates — revise — ambiguity — "Three gates" -> "**Four gates**", area-must-be-`ACTIVE` inserted second with `ERR_RECEIVING_AREA_NOT_ACTIVE`; `finalization_note` not persisted — `routes/receiving.py:197-217`
- §3.8 finalization cascade — insert — ambiguity — the `REDEMPTION` transfer names the holder as `from_party_id` with no transferee/price/`market_transaction_id`; holder holdings recomputed; an already-`PARTIALLY_REDEEMED` certificate stays there; source easements *are* rewritten (version++), unlike the §3.6 retirement carve-out; the area's version increments on every finalization — `routes/receiving.py:221-256`
- §3.8 backing counters — revise — **mismatch** — replaced "counts held rows through `pending_backed_units`" with the actual definitions: `backed_units` = `CONFIRMED` only, `pending_backed_units` = `ALLOCATED` only, `HELD_PENDING_COMPLIANCE` and `RELEASED` count towards neither — `services/derive.py:recompute_application_backing`
- §3.8 enumerations — insert — ambiguity — seven application statuses (`SUBMITTED` never read) and four redemption statuses; filters reject anything else with `ERR_INVALID_REQUEST` — `routes/receiving.py:23-28`
- §3.9 inspection intake — insert — ambiguity — `affected_acres` optional / >= 0 / 2dp / default `0.00` / never bounded by the easement's own acreage; `note` **is** persisted; a future `inspection_date` fails `ERR_INVALID_REQUEST` at rung 4; the 90-day check runs on full instants and is skipped for the first inspection — `routes/easements.py:62-72,91`
- §3.9 inspection intake recording gate — revise — **mismatch** — removed the PRD's false requirement that the easement be `RECORDED`/`AMENDED`; the implementation applies no recording-status gate — `routes/easements.py:57-72`
- §3.9 severity extent — insert — ambiguity — a zero `restricted_acres` yields ratio 1 when `affected_acres` > 0, else 0 — `services/calc.py:violation_severity`
- §3.9 freeze cascade opening — insert — ambiguity — `VIOLATION_NOTICED` is set from *any* prior compliance value, including `UNDER_CURE` and `ESCALATED`; the new deadline replaces the old — `services/derive.py:198-240`
- §3.9 freeze cascade certificates — insert — ambiguity — `lifecycle_status` is not consulted; only formerly-`UNDER_CONTRACT` certificates have transactions cancelled and units released from `units_encumbered`; already-`FROZEN` certificates are untouched and not reported as newly frozen — `services/derive.py:198-240`
- §3.9 freeze/cure versions — insert — ambiguity — the receiving area is reconciled but its `version` is deliberately left untouched by both cascades — `services/derive.py:198-240,246-277`
- §3.9 cure verification states — revise — **mismatch** — `CURE_IN_PROGRESS` is accepted only from `CURE_PENDING`, but `CURED` is accepted from `CURE_PENDING` **or** `ESCALATED`; the SoD check at rung 8 precedes the state test; `verification_note` not persisted — `routes/easements.py:144-149`
- §3.9 `CURE_IN_PROGRESS` — insert — ambiguity — the easement transitions only from `VIOLATION_NOTICED`; a repeat call leaves easement status/deadline/version untouched while the inspection's version still increments — `routes/easements.py:153-157`
- §3.9 `CURED` — insert — ambiguity — the cascade is conditioned on the easement sitting in one of the three violation states; otherwise nothing cascades but the inspection still moves to `CURED` — `routes/easements.py:158-168`
- §3.9 escalation sweep — insert — ambiguity — takes no input, walks ascending `created_at` with insertion-order ties, returns HTTP 200 with empty `data`, nothing-overdue is not an error, an already-`ESCALATED` easement is not re-incremented — `routes/ops.py:28-47`
- §3.9 closing the loop — insert — ambiguity — `CURED -> COMPLIANT` is the only transition a `COMPLIANT` finding makes; against `VIOLATION_NOTICED`/`UNDER_CURE`/`ESCALATED` it changes nothing, though the version still advances via `last_inspection_at`; five inspection statuses including the never-read `OPEN` — `routes/easements.py:106-112`
- §3.9 program evaluation — insert — ambiguity — three required fields; the ordering test runs on instants, not dates; ANY shared day (including containment) is rejected; the sole exception is an exact start+end date match, which supersedes with version++; `SUPERSEDED` rows are invisible to overlap detection; a rejected computation writes nothing — `routes/ops.py:50-89`
- §3.9 `issued_units` — insert — ambiguity — the certificate set is every row whose `issued_at` falls in the window, root and split child alike, whatever its lifecycle or market status, so a split inflates both `issued_units` and `outstanding_units` — `services/calc.py:program_evaluation_metrics`

### Deliberately not written (pass 3)

Two implementation branches are unreachable and got no prose rather than invented behavior: `calc.price_deviation_bps`'s zero-reference guard (`per_unit_value_cents` >= 1 and `equity_adjustment_bps` >= -5000 keep the rounded value >= 1) and `calc.easement_restriction_extent`'s `baseline_units <= 0` branch (a zero baseline fails `ERR_NO_ALLOCABLE_UNITS` before certification). `derive.apply_backing_state` is dead code, inlined at both call sites — not a PRD concern.

### Orchestrator integrity verification

- `wc -l` = 508 (unchanged), `wc -c` = 134,189 vs source 114,717 -> **+19,472 chars**; `cmp` confirms `PRD_COMPLETED.md` is NOT identical to `PRD_FINALIZED.md`, so the scan demonstrably ran.
- All five `## ` headings present; last line is the final row of the §5 error-code table (`| \`ERR_SENDING_CAP_EXHAUSTED\` | 409 |`) — no mid-sentence truncation.
- No difficulty-directive or scaffold-vocabulary leak (`grep -i` for "expert level"/"harder than expert"/"scaffold"/"test_recipe" returns nothing).
- Step 9 edits only the PRD, never `implementation/` or the tests, so the Step 7 clean sweep (8/8 rounds at 126/126) remains valid.

**Pipeline complete.**
