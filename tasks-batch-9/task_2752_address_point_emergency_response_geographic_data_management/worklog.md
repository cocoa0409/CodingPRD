# Worklog — task_2752_address_point_emergency_response_geographic_data_management

## Step 1: Create task directory — 2026-09-04T16:23:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2752_address_point_emergency_response_geographic_data_management` and its `workspace/` subdirectory. Index 2752 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide on auto-allocation).

## Step 2: Generate Scaffold — 2026-09-04T18:20:00.000Z

All three artifacts are complete and the linter is clean.

## Files

| File | Lines | Top-level keys |
|---|---|---|
| `SCAFFOLD.yaml` | 3321 | `scenario, domain_name, api_prefix, response_envelope, envelope_conventions, complexity_profile, entities, cascade_rules, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key present |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2325 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4750 | `scaffold_corner_design` only |

## §1.0–§1.7 surface
14 entities (Jurisdiction, Agency, CoverageCell, RoadCenterline, AddressPoint, AddressAssignmentRequest, EmergencyServiceBoundary, BoundaryCellAssignment, QcValidationReport, QcDefect, ProvisioningPackage, PackageRecord, DiscrepancyCase, DiscrepancyProposal), 64 endpoints under `/gis`, 56 error codes, 32 priority-ordered validations, 13 calculations, 9 state machines, 5 cascade rules, 3 concurrency rules, 6 roles. Profile: `expert_plus`, `temporal_windowing` × `multi_party_negotiation`, topology `graph`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`, layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / version_pinning_on_approval`.

## §1.8 — all 9 difficulty rules covered
25 instances across `dual_variant_calc` (3), `combinatorial_formula` (3), `non_linear_state_machine` (2), `transitive_cascade` (2), `priority_pair_validation_conflict` (4), `boundary_precision_check` (3), `cross_entity_state_dependency` (3), `resource_temporal_overlap` (2), `compensating_invariant` (3).

## §1.9 — all 9 sections, 103 instances (78 real + 25 `excluded_because` stubs)
entities 13, state_machines 21, calculations 16, validations 16, endpoints 5, errors 18, rbac 7, cross_cutting_layers 6, consistency_model 1. Every claim-extraction-guide row is instantiated except rows the scaffold makes inapplicable: `bubble_up` (no all-children-terminal auto-transition exists), `tiered_pricing / topological / decay_function / waterfall_allocation` (no such algorithm declared), `bulk_action` (no bulk endpoint declared).

## Audits
- `scaffold_lint.py`: **VERDICT: clean lint** — 884 calls scanned across §1.8+§1.9, all conform to §1.5, all §1.1 FKs reverse-reachable.
- Error triggerability: **56/56** codes appear in the `assert` block of a real (non-stub) test recipe.
- Instance names unique across the union of both design files (128 names, 0 collisions); every stub's cited `difficulty_instance` exists and no stub carries a `test_recipe`.

## Two things to flag
1. Per the known leak hazard, the directive line "Generate task harder than expert level!" was **omitted from `scenario:`** (it would otherwise propagate into PRD.md); the intent is encoded as `complexity_profile.difficulty_level: expert_plus`. The remaining scenario text is verbatim.
2. `PIN_STALENESS_RULE` was shaped so `ERR_PACKAGE_PINS_STALE` is reachable: destructive drift invalidates a DRAFT/SEALED package, non-destructive drift leaves it SEALED with `drift_detected = true` and is refused at publish by validation priority 27 — the only path to that code.

**Orchestrator verification:** grep of SCAFFOLD.yaml for "harder than"/"expert level" returns 0 hits — the difficulty directive did not leak into the scenario key, so it cannot reach PRD.md. `workspace/` survived the subagent (checked against the known Step 2 wipe hazard). Design keys confirmed absent from SCAFFOLD.yaml.

## Step 3: Copy shared files — 2026-09-04T18:21:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T18:38:00.000Z

PRD.md is complete.

**Output:** `workspace/PRD.md` — **493 lines**, ending at a real section boundary (last row of the §5 table; no audit footer, no contract-report blocks in the file).

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 RBAC · 2.2 API Response Structure (verbatim block) · 2.3 Pagination · 2.4 The Logical Clock and Temporal Representation · 2.5 Record Identity, Timestamps and the `version` Counter · 2.6 Optimistic Concurrency on Parent Records · 2.7 Validation Precedence and Nested Path Resolution · 2.8 Numeric Precision and Rounding · 2.9 Version Pinning, Drift and the Cascade Discipline · 2.10 Segregation of Duties · 2.11 Uniqueness, Immutability and Historical Retention
- §3 Business Logic & Workflows — 3.1 Jurisdictions, Agencies, Coverage Cell Grid · 3.2 Road Centerline Maintenance · 3.3 Address Points, Subaddress Units, Confidence Scoring · 3.4 Assigning Addresses to New Construction · 3.5 Emergency Service Boundaries and Cell Claims · 3.6 QC Scanning, Waivers, Certification · 3.7 Provisioning Releases · 3.8 Discrepancy Negotiation, Adoption, Arbitration · 3.9 Retirement, Supersession, Records Research
- §4 Endpoint Definitions (intro paragraph + 4-column table)
- §5 Error Code Catalogue (2-column table)

**Coverage (documented / present in scaffold)**
| Element | Scaffold | Documented |
|---|---|---|
| Entities | 14 | 14 |
| Entity fields | 130 | 130 (all verbatim in backticks) |
| Endpoints | 64 | 64 (method+path exact match, no extras) |
| Errors | 56 | 56 (all IDs and HTTP statuses match) |
| Validations | 32 | 32 |
| Calculations | 13 | 13 |
| State machines | 9 | 9 (all 34 from/to states present) |
| Cascade rules | 5 | 5 |
| Concurrency rules | 3 | 3 |

**Hard Contract 1 — Field-Name Coverage: PASS.** Mechanical check: all 130 `entities[].fields[].name` values and all 80 endpoint `input` identifiers appear verbatim in backticks. Zero misses.

**Hard Contract 2 — Rule Coverage: PASS.** All 56 error IDs, all 32 validation error IDs with §2.7/§3 precedence orderings, all 3 OCC rules (field + endpoint + error + 412), all 5 cascade rules in prose, all 9 state machines' transitions and states, and every calculation constant value present.

**Hard Contract 3 — §3 Path Purity: PASS.** All backtick tokens in §3 scanned: zero start with `/`, zero are bare HTTP methods, zero combine method+path.

The isolation constraint was honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Orchestrator truncation check (per the known doc-generator failure mode):** `tail -25` shows the §5 error table ending on a complete row (`ERR_CADENCE_WINDOW_NOT_OPEN | 409`), not mid-sentence. Independent recount: 56 `ERR_` rows in PRD vs 56 error ids in SCAFFOLD.yaml; 64 endpoint rows in §4. Section headers run §1 → §5 with all 11 §2 subsections and all 9 §3 subsections present. PRD is NOT truncated; no regeneration needed. Grep for "harder than"/"expert level"/"scaffold" in PRD.md returns 0 hits — the difficulty directive did not reach the PRD.

## Step 6: Generate Implementation — 2026-09-04T19:08:00.000Z

(Steps 5 and 6 were launched as concurrent background subagents; Step 6 returned first, so it is recorded first. Step 5's entry follows below.)

Implementation complete and verified.

## Modules written

`workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `app.py` | 56 | Flask factory, blueprint registration under `/gis`, `ApiError` + 404/405/400/500 handlers |
| `store.py` | 133 | In-memory `db` (14 dicts), logical UTC clock, id/seq minting, `sorted_rows`, `touch` |
| `errors.py` | 85 | All 56 error ids → HTTP status + default messages |
| `envelope.py` | 57 | `{meta, response_type, data}` envelope, `api_request_id` |
| `validate.py` | 343 | Auth/role gate, typed field validators, pagination, FK resolution (`find`/`maybe_find`) |
| `calc.py` | 791 | All 13 calculations (confidence, slot counts, coverage/gap counters, QC defect scan, scores, pin drift, cadence) |
| `serialize.py` | 258 | Per-entity projections with computed counters |
| `cascade.py` | 218 | PIN_STALENESS, JURISDICTION_COUNTER_REFRESH, ROAD_SLOT_REFRESH, CONFIDENCE_REFRESH, retirement + resolution cascades |
| `routes/config.py` | 212 | Jurisdictions, agencies, coverage cells, coverage-status, clock |
| `routes/roads.py` | 208 | Road centerline CRUD + validate/publish/retire |
| `routes/points.py` | 248 | Address points, subaddress units, activate/retire (`mint_point` reused by requests) |
| `routes/requests.py` | 268 | Assignment requests: gis-review, utility-clearance, assign, void |
| `routes/boundaries.py` | 254 | Boundaries + cell claims, propose/activate/retire |
| `routes/qc.py` | 213 | QC reports, defect waivers, certify/reject |
| `routes/packages.py` | 208 | Packages, records, seal/publish/rollback |
| `routes/disc.py` | 256 | Discrepancy cases, proposals, concur/adopt/arbitrate |
| `start.sh` | 10 | Conditional flask install, `exec python3 app.py`, `PORT` default 10000 |

Total 3820 lines. No `__pycache__` left behind.

## Coverage vs scaffold

- Endpoints: introspected route table reports exactly **64** `/gis` endpoints — parity with the scaffold's 64.
- Errors: `errors.HTTP_STATUS` holds exactly **56** ids.
- Entities: 14 dicts, all empty at import, clock at `2026-08-01T00:00:00Z`. No seeding; a grep for `sqlite|shelve|pickle|open(...'w'|json.dump` finds nothing.
- All 9 state machines and 32 priority-ordered validations are wired; validation order follows PRD §2.7 (401 → 403 → agency identity → path 404 → FK 404 → 400 → 409 → 412 → 422).

## Smoke test (port 18752, ~90 calls, then killed by its own PID)

End-to-end happy path plus negative paths all behaved as contracted, including:

- `401 ERR_UNAUTHENTICATED`, `403 ERR_UNAUTHORIZED`, `404 ERR_ROAD_NOT_FOUND`, `400 ERR_INVALID_REQUEST` on `limit=0`
- Road lifecycle: normalization (`N. Maple St` → `N MAPLE STREET`), `422 ERR_RANGE_GEOMETRY_INVALID`, `412 ERR_STALE_ROAD_VERSION`, DRAFT→VALIDATED with `qc_dirty` cleared
- Points: parity/range/duplicate/subaddress rejections, provisional confidence 91.00 (base) vs 73.00 (unit), slot count dropping 50→49
- Requests: duplicate permit 409, `ERR_REQUEST_NOT_READY` before both dimensions clear, assign minting house 102 + 3 points, void reclaiming the slot
- Boundaries: `ERR_AGENCY_IDENTITY_MISMATCH`, `412 ERR_STALE_BOUNDARY_VERSION`, DRAFT→PROPOSED→ACTIVE, cell coverage flipping to `covered:['LAW'] gap:['FIRE','EMS']`
- QC: 5 defects scanned (4 blocking), `ERR_QC_BLOCKING_DEFECTS_OPEN`, waivers raising quality 81.30→98.80 (tier C→A, eligibility 94.80), `ERR_SEGREGATION_OF_DUTIES` on self-certify, certification stamping `certified_confidence_score`
- Packages: seal (v1, 2 pinned records), SoD-blocked publish, publish, `ERR_NO_PUBLISHED_PREDECESSOR`, second publish superseding v1, rollback restoring v1 to PUBLISHED
- Discrepancy: `ERR_COUNTERPARTY_INVALID`, `ERR_SUBJECT_CASE_ALREADY_OPEN`, road frozen (`ERR_ROAD_FROZEN_BY_DISCREPANCY` on publish), `ERR_SELF_CONCURRENCE` on both self-counter and self-concur, concur→adopt cascading a road rename, road demoted to `qc_dirty`, point reverting to PROVISIONAL, report → `DECERTIFIED / SUBJECT_RECORD_CHANGED`
- Road retire cascading points to `ROAD_RETIRED` and units to `PARENT_RETIRED`; `include_retired` returning 5 rows vs 0 by default

After a final edit (dropped an unused import in `packages.py`) I recompiled everything and re-booted on port 18753 — `GET /gis/jurisdictions` returned 200 — then killed that listener by pid. Both ports confirmed free; no broad pkill was used.

## Step 5: Generate Unit Tests — 2026-09-04T19:16:00.000Z

The test suite is complete and audited.

## Files written (task root, not under `workspace/`)

**`test_helpers/` — 2,604 lines, 9 modules**: `__init__.py` 121, `api_client.py` 485 (one method per endpoint + `api_client` singleton), `api_errors.py` 138 (all 56 codes + registered HTTP-status map), `assertions.py` 390, `constants.py` 146, `factories.py` 311, `fixtures.py` 724 (five-tier composite setup), `test_users.py` 83 (incl. `make_agency_liaison_headers` for the entity-backed role), `types.py` 306.

**`test_suite/` — 8,364 lines, 18 files, 162 tests**: `conftest.py` 49; `test_01` 372/8, `test_02` 370/7, `test_03` 331/6, `test_04` 317/5, `test_05` 324/8, `test_06` 426/6, `test_07` 239/6, `test_08` 231/5, `test_09` 329/6, `test_10` 710/14, `test_11` 674/11, `test_12` 659/11, `test_13` 319/5, `test_14` 873/17, `test_15` 947/20, `test_16` 727/19, `test_17` 367/8 (lines/tests).

## Instance-to-test mapping

- **Queue A (difficulty)**: 25/25 instances translated, 57 tests, every instance >=2 tests (min was 2).
- **Queue B (corner)**: 78/78 non-stub instances translated, 105 tests, every instance >=1 test. All 25 `excluded_because:` stubs correctly emitted nothing.
- **Skipped instances: none.** No instance failed the PRD-first filter, so there are no PRD-silence or non-unique-derivability gaps to report.

## Verification the subagent ran itself

- Parsed all 162 test functions with `ast`: every signature is exactly `(api)`; every docstring ends with exactly **one** `Design:` line; all 162 tags resolve to a real instance in the source yaml (cross-checked against a canonical 103-tag set extracted independently — 25 difficulty + 78 real corner); zero unknown, dual or stub tags.
- Verbatim citation check: all 162 tests carry at least one PRD sentence that is a byte-exact substring of `workspace/PRD.md` (0 failures after stripping the `PRD:` label prefix).
- `python3 -m py_compile` clean on all 27 modules; `pytest --collect-only` collects exactly 162 tests in 1.2s.
- Static symbol resolution across all test files: every `api.*`, `ApiErrorId.*`, `fx.*` and factory reference exists — 0 unresolved.
- `test_helpers/` and `test_suite/` are at the task root; nothing stray under `workspace/`; `__pycache__` cleaned. Nothing in `workspace/implementation/` was read, listed or written; no server started or killed; no `pkill`.

## Three PRD defects the translation surfaced (worth fixing at Step 8/9)

1. **`open_discrepancy_case_count` vs `CONCURRED`** — §3.8 defines the counter over `OPEN`, `PROPOSAL_PENDING`, `COUNTERED`, `ESCALATED` (so `CONCURRED` => 0), but §3.2 says the freeze lifts only at adopt/arbitrate and §3.8 says the count drops to zero at adoption (=> 1). That single assertion was omitted rather than guessed; the instance is otherwise fully covered.
2. **`package_version` at seal** — the corner yaml asserts it stays null after sealing; §3.7 says seal assigns the channel-scoped version. Two such assertions were omitted (the `== 1` after publish is kept).
3. **`ERR_REQUEST_NOT_READY` vs `ERR_REQUEST_INVALID_STATE`** — §2.7's generic sentence points at `NOT_READY` for any wrong fulfillment dimension, while §3.4 reserves it for `assign` only. Tests follow §3.4 (matching the yaml).

Also, two yaml recipes use enum values the PRD does not define (`subject_type: ROAD_RANGE`, `jurisdiction_type: CITY`); the tests substituted valid values so the asserted 201/409 remains the first failing check.

**Orchestrator verification:** `find workspace -type d -name 'test_*'` returns nothing — no stray test dirs landed under `workspace/` (the known Step 5 misplacement hazard did not fire). 18 files in `test_suite/`, 9 in `test_helpers/`, both at the task root. Removed a leftover `test_helpers/__pycache__`.

## Step 7: Run Tests and Iterate — 2026-09-04T19:44:00.000Z

GREEN. All 8 parallel rounds: 162/162 passed, 0 failed, 0 errors, 0 skipped.

## Summary

**Iterations run:** 2 sweeps (1 diagnostic pre-fix, 1 verification post-fix). Pre-fix: 155/162, the same 7 tests failing deterministically in all 8 rounds (no flakiness). Post-fix: 162/162 in every round, union of non-passing tests across all 8 results files = 0.

**Tests deleted:** none. Every failure traced to a verbatim PRD sentence, so no test hit a PRD-silence or unique-derivability collapse pattern. No assertion was weakened, no skip/xfail added.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none. Two failures looked like implementation over-increments; proved with an out-of-tree probe that every increment traces to PRD (§3.2 publication triggers a confidence refresh, §2.9 each refreshed point increments its own version by 1, §3.3 activation +1, §3.6 certification stamps and increments each point). Storage remains in-memory only; nothing was seeded, added, or removed.

**Fixes applied to `test_suite/` (6 edits, all STEP 2 test-vs-PRD faithfulness corrections):**

1. `test_suite/test_03_parallel_state_machines.py` — helper `_cleared_but_unreviewed_request` asserted `utility_status="UTILITY_PENDING"`; PRD §3.4 says the dimension "begins at `PENDING_UTILITY`". Fixed the literal; repaired 3 tests sharing the helper (the triage-hint pattern: >=3 failures sharing one helper).
2. `test_12_calculation_surface.py` — `test_overlap_detection_compares_left_against_a_peer_right_range_rejected` built its "same normalized name" peer as `"North Maple Street"`, which normalizes to `NORTH MAPLE STREET` because PRD expands abbreviations only in the LAST token; the test then asserted `normalized_name="N MAPLE STREET"`. Changed the peer to `"N. Maple Street"`.
3. `test_15_error_surface.py` — `test_activating_an_already_active_point...`: expected point `version == 2`, but the same test already asserted `confidence_score == 96.00`, which only holds if the publish-triggered refresh ran (and that refresh increments the version). Internally inconsistent; corrected to 3.
4. `test_15_error_surface.py` — `test_gis_review_on_a_voided_request...`: expected `ERR_REQUEST_INVALID_STATE`. A VOIDED request under gis-review violates only the fulfillment dimension (review_status is still PENDING_REVIEW), and §2.7 states "when the fulfillment dimension is wrong for the requested action the code is `ERR_REQUEST_NOT_READY`". Corrected to the exact code `ERR_REQUEST_NOT_READY` (exact->exact, not a downgrade to a status check). Confirmed no test exercises the utility-clearance-on-closed-request path where §3.4 does name INVALID_STATE for a fulfillment violation, so the implementation's asymmetry there stays PRD-literal.
5. `test_15_error_surface.py` — `test_publishing_a_sealed_package_whose_point_pin_went_stale_is_refused`: point `version` 4->5 and `pinned_version` 3->4, per the same publish-refresh increment.

**Method note:** because the runner has no `-k` selector, the agent built a throwaway per-test-server pytest plugin under `/tmp/t2752/` (never inside the artifact tree, no test artifact modified for convenience) giving a 107-second full-suite loop; the authoritative verdict is the 8-round sweep above. `worklog.md` was not touched by the subagent. `__pycache__`/`.pytest_cache` cleaned; no leftover processes for this task.

**Orchestrator verification (per the known "clean sweep with no artifacts" hazard):** independently read all 8 `workspace/implementation/results.$i.json` files after the notification — every round reports `passed 162 / total 162`. The pre-fix sweep was also read directly and showed a uniform 155/162 across all 8 rounds, confirming the 7 failures were deterministic rather than load-induced, so no re-run was needed to rule out contention. Step 8 is NOT skipped: the skip condition requires zero fixes in all four categories, and Step 7 made 6 `test_suite/` edits.

## Step 8: Finalize PRD — 2026-09-04T19:53:00.000Z

## Line counts
- `PRD.md`: 493 lines. `PRD_FINALIZED.md`: 493 lines. **0% line delta**; 5 lines revised in place (~1.0% of lines touched), no sections added or removed.

## Changes (one bullet each)
- **§2.7 (validation precedence / request code split)** — revise — appended a declared exception so the generic "wrong fulfillment dimension => `ERR_REQUEST_NOT_READY`" rule no longer contradicts §3.4's utility rule; the utility action reports a closed fulfillment dimension as `ERR_REQUEST_INVALID_STATE` — `implementation/routes/requests.py:158-161`.
- **§3.4 (GIS review)** — revise — pinned the precondition order (review dimension first) and named both codes: already-reviewed => `ERR_REQUEST_INVALID_STATE`; still `PENDING_REVIEW` but fulfillment left `OPEN` (e.g. VOIDED) => `ERR_REQUEST_NOT_READY` — `implementation/routes/requests.py:130-135`.
- **§3.2 (contested-centerline freeze)** — revise — "The freeze lifts only when the case is adopted or arbitrated" replaced: the freeze lifts as soon as the case's status leaves the four counted values, so a `CONCURRED` case no longer freezes the road — `implementation/calc.py:372-379`, `implementation/routes/roads.py:37-39`, `implementation/routes/points.py:213`.
- **§3.8 (adoption, level 1)** — revise — "`open_discrepancy_case_count` consequently drops to zero and the centerline unfreezes" replaced by the impl-true statement that the counter stopped counting the case at `CONCURRED`; also avoids the false universal "drops to zero" (two cases, `ROAD_NAME` + `ADDRESS_RANGE`, can co-exist on one road) — `implementation/calc.py:375-379`, `implementation/routes/disc.py:213,223-234`.
- **§3.7 (sealing)** — revise — made explicit that the release number is written into `package_version` at seal time and never changed afterwards — `implementation/routes/packages.py:117`, `implementation/calc.py:502-513`.

No edit was made for Step 7 items 1, 2, 3 and 5 (utility_status literal `PENDING_UTILITY`, last-token abbreviation expansion, publish-triggered confidence refresh incrementing each point's version): each is already uniquely determined by verbatim PRD prose (§3.4, §3.2 five-step normalisation, §3.2 publication + §2.9 refresh discipline), and those Step 7 fixes were pure fixture bugs.

## Per-edit pre-edit search log
1. **§2.7 request codes.** (a) Subject: which 409 code each address-assignment-request action returns for each wrong dimension. (b) Enumerated: `grep -rn "ERR_REQUEST"` over `implementation/` → `errors.py:38-39`, `validate.py:300`, and all four action sites in `routes/requests.py` — `gis_review` 130/134, `utility_clearance` 158/163, `assign` 184, `void` 253; each read in full. (c) Wording adjustment: scoped the exception to "the utility action" only, so `void`'s and `assign`'s `NOT_READY` and `utility_clearance`'s repeat-transition `INVALID_STATE` all stay correctly described.
2. **§3.4 review order.** (a) Subject: precondition evaluation order inside gis-review. (b) Enumerated: `routes/requests.py:122-147` (only gis-review site); cross-checked `validate.py` auth/find ordering and §2.7's global ladder to confirm the two dimension checks sit after schema validation (`v.body()`/`req_enum` precede them at 126-128). (c) None needed; used "a voided request, for instance" rather than an exhaustive list so `FULFILLED`/`CLOSED_REJECTED` (which fail the review check first) are not mis-described.
3. **§3.2 freeze lift.** (a) Subject: the set of case statuses that make `open_discrepancy_case_count` non-zero, and therefore when the road freeze applies. (b) Enumerated: `calc.py:372-379` (definition), `routes/roads.py:37-39` `_assert_not_frozen` and its four callsites (edit 131, validate 157, publish 183, retire 200), `routes/points.py:213` (activate), `calc.py:224` (certified-variant -20 penalty), `serialize.py:72` (road read). All read the same 4-status counter. (c) Wording adjustment: phrased as "leaves the four values the counter counts" instead of asserting the count becomes zero, since two cases (`ROAD_NAME` and `ADDRESS_RANGE`) can be open on the same centerline.
4. **§3.8 adoption level 1.** (a) Subject: the counter's value at adoption and what unfreezes. (b) Enumerated: `routes/disc.py:192-216` (concur), `219-236` (adopt, only reachable from `CONCURRED`), `239-256` (arbitrate, reached from `ESCALATED` where the count really does drop), `cascade.py:169-218` (levels 2-5), plus the same counter paths as edit 3. (c) Wording adjustment: confined the claim to "this case" and to the adoption paragraph, so the arbitration path (where level 1 does drop the count from 1 to 0) and multi-case roads are not mis-described.
5. **§3.7 seal `package_version`.** (a) Subject: when `package_version` is written and whether anything later mutates it. (b) Enumerated: `grep -rn "package_version"` → `routes/packages.py:36` (create => null), `:117` (sole write, at seal), `:200` (rollback reads only), `calc.py:502-513` (`next_package_version`), `serialize.py:202`; also confirmed `publish_package`, `rollback_package` and `cascade.invalidate_package` never touch the field. (c) None needed; "never changed afterwards" verified true across every enumerated path.

**Orchestrator verification:** `cmp` confirms `PRD_FINALIZED.md` is NOT byte-identical to `PRD.md` — the patch really landed (5 changed lines, 493 → 493). Step 8 was correctly not skipped, since Step 7 made 6 `test_suite/` edits.

## Step 9: Complete PRD — 2026-09-04T20:35:00.000Z

Step 9 was run as **three sequential, module-partitioned passes over one shared `PRD_COMPLETED.md`** rather than as a single subagent. Rationale (orchestrator decision, no user available to consult): the implementation is 3809 lines across 17 modules, and a single subagent attempting an exhaustive PRD-vs-impl scan of that surface reliably either exhausts its context or short-circuits into a no-op `cp` that leaves `PRD_COMPLETED.md` byte-identical to its source. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying (a re-copy would silently destroy the prior passes' work). Slices were disjoint by impl module, with `calc.py` split by subject area.

### Pass 1 — app.py, store.py, envelope.py, errors.py, validate.py, serialize.py, routes/config.py
`cp PRD_FINALIZED.md -> PRD_COMPLETED.md` confirmed as first action. 493 lines / 115,711 chars -> 494 lines / 121,222 chars (+1 line, +5,511 chars). **14 ambiguity-pins, 2 mismatch-revisions.**

- §2.1 — revise — ambiguity — whitespace-only `X-User-ID` counts as absent (401); missing `X-User-Role` or any value outside the six role names is `ERR_UNAUTHORIZED` 403 not 401 — `validate.py:26-31`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars, minted per request incl. errors — `envelope.py:13-14`
- §2.2 — revise — ambiguity — `api_request_timestamp` reads the logical clock, not the wall clock — `envelope.py:20`
- §2.3 — revise — ambiguity — a `limit`/`offset` that is not a plain base-10 integer literal is `ERR_INVALID_REQUEST` — `validate.py:234,241`
- §2.3 — revise — ambiguity — `created_at` ties break by creation sequence; all list filters exact-equality and conjunctive; enum filters validated; boolean filters accept `true/false/1/0` any case — `store.py:127`, `validate.py:249-274`
- §2.4 — revise — ambiguity — the clock accepts any valid instant, including one earlier than its current value — `routes/config.py:206-212`
- §2.4 — revise — ambiguity — inbound datetimes: >3 fractional digits truncated (never rounded) to ms; no zone designator read as UTC; numeric offsets converted to UTC; lowercase `t`/`z` and a space separator tolerated — `store.py:52-87`
- §2.7 — revise — ambiguity — a *body* reference resolves only when a non-empty string (wrong-typed/blank gives 400 not 404); a *query filter* reference resolves as supplied (empty filter value gives the not-found code) — `validate.py:213-223,327-338`
- §2.7 — revise — ambiguity — non-JSON or non-object body -> `ERR_INVALID_REQUEST`; absent/empty body read as `{}`; undeclared fields ignored; strings trimmed only for the blank check, length measured and stored untrimmed — `validate.py:38-50,73-85`
- §2.9 — revise — ambiguity — every counter is a read-time re-derivation, so recomputation never bumps the holder's `version`/`updated_at` nor flips a pin; `Jurisdiction` and `CoverageCell` stay at `version` 1 forever — `serialize.py:1-6`, `store.py:130-133`
- §3.1 — revise — ambiguity — `postal_city` is non-blank — `routes/config.py:29`
- §3.1 — revise — ambiguity — `contact_phone` <=40 chars, empty string accepted, stored verbatim — `routes/config.py:80`
- §3.1 — revise — **mismatch** — suspension has no state precondition and no inverse: re-suspending a `SUSPENDED` agency succeeds again, overwriting `suspended_reason` and bumping `version` (contradicted §2.7's "idempotency is not granted anywhere"); `suspended_reason` required, non-blank, unbounded — `routes/config.py:122-131`
- §3.1 — revise — ambiguity — `centroid_lat`/`centroid_lon` range-checked (-90..90 / -180..180) despite being informational — `routes/config.py:144-145`
- §4 — revise — **mismatch** — unmatched path -> `ERR_NOT_FOUND` (404); known path with unoffered method -> `ERR_INVALID_REQUEST` at **405** (§5 listed that id as 400-only); both decided before authentication; trailing slashes accepted — `app.py:20,30-36`
- §5 — insert — ambiguity — added the missing `ERR_NOT_FOUND | 404` row and annotated `ERR_INVALID_REQUEST`'s 405 case — `errors.py`/`app.py:32`

Cross-checks: machine-diffed `errors.HTTP_STATUS` against the §5 table — all 56 codes match exactly. Verified every `serialize.py` emitted field name (incl. all `calc` counter keys) already appears in the PRD. Verified every list endpoint routes through `store.sorted_rows` and every list filter is exact equality before asserting those universals; verified no code path calls `touch()` on a jurisdiction or cell.

### Pass 2 — calc.py (roads/points/requests formulas), cascade.py, routes/roads.py, routes/points.py, routes/requests.py
No re-copy (confirmed; all 16 Pass-1 paragraphs intact). 494 -> 494 lines, 121,222 -> 125,429 chars (+4,207). **17 ambiguity-pins, 2 mismatch-revisions** (19 edits over 13 paragraphs).

- §3.2 creation — insert — ambiguity — the "parities must differ" rule is schema-level (`ERR_INVALID_REQUEST`, not `ERR_RANGE_GEOMETRY_INVALID`), evaluated before geometry on create and against the *merged* parities ahead of state/version/freeze/geometry on edit — `routes/roads.py:55,121`
- §3.2 creation — insert — ambiguity — new centerline's `retired_at` and `retire_reason` are null — `routes/roads.py:71`
- §3.2 publication — insert — ambiguity — a `VALIDATED` road left `qc_dirty` is refused `ERR_ROAD_INVALID_STATE`, and that check precedes the discrepancy-freeze check — `routes/roads.py:180`
- §3.2 retirement — revise — ambiguity — `retire_reason` required, non-blank, no upper length bound — `routes/roads.py:196`
- §3.3 creation — insert — ambiguity — body references resolve centerline -> cell -> parent, so multiple bad ids report `ERR_ROAD_NOT_FOUND` — `routes/points.py:73`
- §3.3 creation — insert — ambiguity — centerline `status` is not a creation precondition (authoring against `RETIRED` or frozen roads succeeds; the gate is at activation) — `routes/points.py:73`
- §3.3 confidence — **revise — mismatch** — the provisional variant sets `confidence_basis`/`certified_confidence_score` only at creation; a later activation or refresh rewrites `confidence_score` alone and preserves an existing `CERTIFIED` basis and score (only the §3.8 cascade clears them) — `routes/points.py:222`, `cascade.py:86`
- §3.3 confidence — insert — ambiguity — road-status penalty is also 0 for a `RETIRED` centerline — `calc.py:213`
- §3.3 retirement — revise — ambiguity — `retire_reason` required, non-blank, no upper length bound — `routes/points.py:234`
- §3.4 creation — revise — ambiguity — `proposed_house_number` must be 0-999999 when supplied — `routes/requests.py:54`
- §3.4 creation — insert — ambiguity — initial `minted_point_count` 0 and `assigned_*`/`review_note`/`utility_note`/`void_reason` null — `routes/requests.py:72`
- §3.4 GIS review — revise — ambiguity — `review_note` <=500 chars, may be empty, defaults null — `routes/requests.py:128`
- §3.4 utility — revise — ambiguity — `utility_note` <=500 chars, may be empty, and an omitted note on a later cycle leaves the prior note in place — `routes/requests.py:156`
- §3.4 utility — insert — ambiguity — a decision matching the current utility value is refused `ERR_REQUEST_INVALID_STATE`, checked after the `fulfillment_status` gate — `routes/requests.py:163`
- §3.4 mint — insert — ambiguity — base point's `house_number_suffix`/`latitude`/`longitude` null; every unit inherits the base's `jurisdiction_id`, `cell_id`, `postal_city` and `geometry_verified` false — `routes/requests.py:214`
- §3.4 void — revise — ambiguity — `void_reason` required/non-blank/unbounded; `assigned_house_number`, `assigned_address_point_id` and `minted_point_count` are retained — `routes/requests.py:252`
- §3.4 void — **revise — mismatch** — the swept set is the base point plus *every* point whose `parent_address_point_id` is that base (including units authored later, not only those the assignment minted), and already-terminal points are skipped keeping their existing reason/stamp — `routes/requests.py:30,263`
- §3.8 adoption level 2 — insert — ambiguity — the tolerant free-text parse of an `ADDRESS_RANGE` resolved value (`RIGHT` token selects side else left, first two digit runs become bounds and are swapped if inverted, `EVEN`/`ODD` overrides parity with `EVEN` winning, <2 digit runs leaves the range untouched while the cascade continues, and the written range is never re-checked against §3.2 geometry) — `cascade.py:138`
- §3.8 adoption — insert — ambiguity — a `BOUNDARY_CELL` case performs level 1 only; levels 2-5 do not run — `cascade.py:171`

### Pass 3 — routes/boundaries.py, routes/qc.py, routes/packages.py, routes/disc.py + calc.py (QC scoring, package/pin/cadence, discrepancy counters)
No re-copy (confirmed; Pass 1 and Pass 2 hunks all still present — 47 changed-line hunks, up from 27). 494 -> 494 lines, 125,429 -> 130,303 chars (+4,874). **20 ambiguity-pins, 4 mismatch-revisions.**

- §3.1 — revise — mismatch — "overlap reachable only through pending rows, because activation refuses active overlaps outright" was false: activation only compares against *other* boundaries, so one boundary claiming a cell twice over intersecting windows yields two ACTIVE covering rows — `routes/boundaries.py:180-187`
- §3.5 — insert — ambiguity — a cell claim increments the parent boundary's `version` by 1 (second claim must carry the new value) and evaluates pin staleness; the assignment row lands at `version` 1 — `routes/boundaries.py:126-127`
- §3.5 — insert — ambiguity — proposing a boundary with no claims is `ERR_BOUNDARY_INVALID_STATE` (PRD named no code) — `routes/boundaries.py:154-156`
- §3.5 — revise — mismatch — the activation non-intersection test is against `ACTIVE` claims of a *different* boundary only; sibling claims are never compared — `routes/boundaries.py:181`
- §3.5 — insert — ambiguity — boundary `retire_reason` required, non-blank, no upper length bound — `routes/boundaries.py:206`
- §3.6 — insert — ambiguity — a `FULL`-scoped report forbids both scope fields; both refs resolve before the pairing check, jurisdiction first, so a `FULL` payload with an unresolvable `jurisdiction_id` answers 404 not 400 — `routes/qc.py:27-47`
- §3.6 — insert — ambiguity — `FULL`-scoped scan = every centerline in the system + their non-terminal points + no cells; `RETIRED` centerlines stay in scope (unlike terminal points) — `calc.py:652-667`
- §3.6 — revise — mismatch — "A `ROAD`-scoped report therefore never emits a boundary-category finding" -> `ROAD`-**or**-`FULL`-scoped — `calc.py:731,757`
- §3.6 — insert — ambiguity — defect creation order: `defect_code` compared as a plain string, ties by subject creation sequence, multi-row subjects in fixed `LAW`/`FIRE`/`EMS` order — `calc.py:789-790`
- §3.6 — insert — ambiguity — at most one `ROAD_RANGE_OVERLAP` row per centerline; detail names the first conflict (left interval first, peers in `created_at` order) — `calc.py:145-163,704`
- §3.6 — insert — ambiguity — `BOUNDARY_COVERAGE_GAP` rows anchor to the cell as `entity_type` `COVERAGE_CELL` — `calc.py:762-765`
- §3.6 — insert — ambiguity — `PROPOSED_COVERAGE_OVERLAP` draws its pair from `PENDING`/`ACTIVE` claims only, one row per cell-and-service-type pairing, anchored to the cell — `calc.py:282-300,766-771`
- §3.6 — insert — ambiguity — `BOUNDARY_STALE_WINDOW`: null `effective_end` never qualifies; one row per qualifying claim anchored to the claim's *cell* — `calc.py:774-787`
- §3.6 — insert — ambiguity — `waiver_reason` required/non-blank/unbounded; the response body is the waived defect, not the re-scored report — `routes/qc.py:149,164`
- §3.6 — insert — ambiguity — `rejection_reason` required, non-blank, no upper length bound — `routes/qc.py:205`
- §3.7 — insert — ambiguity — package-open resolves jurisdiction then report before the schema pass, and consults neither the report's status nor its scores — `routes/packages.py:24-28`
- §3.7 — insert — ambiguity — package-record ordering is lexicographic, so `ADDRESS_POINT` -> `EMERGENCY_SERVICE_BOUNDARY` -> `ROAD_CENTERLINE`, not the declared enumeration order — `calc.py:547`
- §3.7 — insert — ambiguity — `rollback_reason` required, non-blank, no upper length bound — `routes/packages.py:187`
- §3.8 — insert — ambiguity — `subject_type` validated before either reference resolves; the acting `X-User-ID` must name a stored `Agency` (`ERR_AGENCY_IDENTITY_MISMATCH`) and that check runs *after* refs and schema, unlike §2.1's ownership rules — `routes/disc.py:36-47`
- §3.8 — insert — ambiguity — proposal `rationale` <=500 chars, defaults null, stored verbatim — `routes/disc.py:139`
- §3.8 — insert — ambiguity — a `proposal_id` that resolves but is not the case's current proposal (or belongs to another case) is `ERR_CASE_INVALID_STATE` — `routes/disc.py:204-208`
- §3.8 — insert — ambiguity — `arbitration_value` is 1-120 chars; arbitration `rationale` <=500 chars is schema-checked but persisted nowhere — `routes/disc.py:244-245`
- §3.8 — revise — mismatch — filing is refused on any case not `OPEN`/`PROPOSAL_PENDING`/`COUNTERED`, which includes `CONCURRED` and `ESCALATED`, not only "already-resolved" — `routes/disc.py:20,141-144`
- §3.8 — insert — ambiguity — case filters: agency/jurisdiction/`current_proposal_id` are resolved (404 on unknown) while `subject_ref_id` is an unresolved plain match (empty page) — `routes/disc.py:93-124`

### Step 9 totals and orchestrator verification
**59 edits total across the three passes: 51 ambiguity-pins, 8 mismatch-revisions.** `PRD_FINALIZED.md` 493 lines / 115,711 chars -> `PRD_COMPLETED.md` 494 lines / 130,303 chars (+1 line, +14,592 chars, +12.6%).

- `cmp` confirms `PRD_COMPLETED.md` is **NOT** byte-identical to `PRD_FINALIZED.md` — the scan genuinely ran in all three passes (the known Step 9 no-op failure mode did not fire). 101 changed lines in the diff vs `PRD_FINALIZED.md`.
- Section-header count is 28 in both `PRD.md` and `PRD_COMPLETED.md` — no new sections were added, as the minimal-patch rule requires.
- `PRD_COMPLETED.md` ends at a real section boundary (final row of the §5 error table), not mid-sentence.
- Grep for "harder than"/"expert level" in `PRD_COMPLETED.md` returns 0 — the difficulty directive never reached any PRD variant.
- Step 9 touched no code, so the Step 7 verdict still stands: all 8 `workspace/implementation/results.$i.json` re-read after Step 9 and every round still reports 162/162.
- Removed a leftover `workspace/implementation/__pycache__`.

**PIPELINE COMPLETE.**
