# Worklog — task_2427_pre_engineered_metal_building_systems

## Step 1: Create task directory — 2026-09-02T16:05:22.503Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2427_pre_engineered_metal_building_systems` and its `workspace/` subdirectory. Index 2427 was pre-assigned by the invoking pipeline (no `./tasks/` scan performed, per orchestration instructions — up to 32 pipelines run concurrently on this host and auto-allocation would collide).

## Step 2: Generate scaffold — 2026-09-02T17:37:06.218Z

Scaffold generation for **task_2427_pre_engineered_metal_building_systems** is complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_2427_pre_engineered_metal_building_systems/`, and the hard constraint was honoured throughout — no sibling task directory was listed, globbed, grepped or read; everything was derived from the scenario text plus the scaffold-generator skill and its `references/claim-extraction-guide.md`.

Final lint (run from the repo root as `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2427_pre_engineered_metal_building_systems`):

```
Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     12
  §1.8 instances scanned:     21
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  1138

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Worklog summary

**SCAFFOLD.yaml** (§1.0–§1.7, 2515 lines) — domain `pre-engineered-metal-building-systems`, archetype `workflow_orchestration` + `pricing_engine`, difficulty "beyond Expert".
- **12 entities**: Jurisdiction, Builder, BuildingConfiguration, AccessoryKit, Quote, EngineeringDesign, DesignComponent (`common_fields: false`, immutable), DrawingPackage, Order, ProductionLine, ProductionLot, ShipmentLoad. Topology flat.
- **8 state machines**, shape `parallel` (Order carries `engineering_status` × `production_status`, the latter compound from its ProductionLot children; Builder/Configuration/Design cyclic).
- **2 OCC rules** (§1.2.1): `design-create-stale-configuration` (`expected_configuration_version`, 412) and `load-create-stale-order` (`expected_order_version`, 412, also on release / cancel-release).
- **11 calculations**, 2 dual-variant: ASD/LRFD load-combination + required moment (qz = 0.00256·Kz·V², M = w·L²/8), pinned per-line weight rounding, PRELIMINARY vs FINAL quote pricing with freight-inclusive volume tiers, builder credit ledger, order shippable-weight ledger, load gross weight, half-open line windows with paint changeover buffer, closed aggregate site-unload windows, production-status rollup, erection-sequence projection.
- **47 ordered validations** across priorities 1–15; **47 error codes**; **50 endpoints**; **8 roles** (`role_model: segregation_of_duties`, all GETs shared by all eight); logical clock default `2026-08-01T00:00:00Z` with `POST /_clock/set_current_utc` the only `/_` endpoint.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8) — 9 rule_ids / **21 instances**: dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 2, transitive_cascade 2 (depth 5 and depth 3), priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9) — all 9 taxonomy sections, **85 instances = 55 full test recipes + 30 `excluded_because` stubs**: entities 12/12 full, state_machines 14 (8 full), calculations 12 (4 full), validations 9 (5 full), endpoints 5/5 full, errors 19 (9 full), rbac 7/7 full, complexity_layers 6 (4 full), consistency_model 1/1 full.

Verified mechanically beyond the lint: all 47 error codes are reachable across §1.8 ∪ §1.9 (the nine 404s, `ERR_BUILDER_CREDIT_EXCEEDED` 402 and `ERR_SEAL_LICENSE_STATE_MISMATCH` got dedicated positive triggers because §1.8 only asserts them as the *losing* rule); every instance name is unique across both files; every stub cites an existing §1.8 instance by name and carries no `test_recipe`; no forbidden write-conflict vocabulary appears anywhere.

## Step 3: Copy shared files — 2026-09-02T17:37:28.281Z

Copied `./INSTRUCTION.md` → `tasks/task_2427_pre_engineered_metal_building_systems/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T17:48:40.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2427_pre_engineered_metal_building_systems/workspace/PRD.md` — **419 lines**, last heading **`## 5. Error Code Catalogue`**, ending at a complete final table row (`ERR_BUILDER_CREDIT_EXCEEDED | 402 Payment Required`). No truncation, no audit footer in the file.

**Structure:** §1 Introduction (3 paras, pain-point angle) · §2 with 12 domain-derived subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination and Collection Filters, 2.4 Resource Identity/Timestamps/Logical Clock, 2.5 Precedence of Request Checks, 2.6 Path Resolution and Referential Failure Codes, 2.7 Measurement Precision and Rounding Discipline, 2.8 Version Pinning on Cross-Aggregate Writes, 2.9 The Two Conserved Ledgers, 2.10 Cascade Propagation/Holds/Void Semantics, 2.11 An Order's Two Independent State Dimensions, 2.12 Enumerated Vocabularies) · §3 with 9 subsections grouped as a business-process timeline (jurisdiction → builder network → configuration/lock → kits+pricing → issue/accept/order → engineering design → sealing → release/plant → shipment sequencing) · §4 50-row 4-column table · §5 47-row 2-column table.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 121 required, 121 present, 0 missing
- endpoints[].request_body: 60 required, 60 present, 0 missing
- endpoints[].query_params: 18 required, 18 present, 0 missing
- computed-read output shapes (erection-sequence, clock): 7 required, 7 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 47 checked, 47 expressed in prose (global 15-band precedence in §2.5 + per-operation orderings in §3.5/3.7/3.8/3.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_configuration_version / expected_order_version + error_id + HTTP 412 all named; §2.8 also extends expected_order_version to release and cancel-release per validations[]), 0 missing
- state_machines[].transitions: 30 checked (Builder 3, BuildingConfiguration 3, Quote 2, EngineeringDesign 6, DrawingPackage 2, Order 8, ProductionLot 3, ShipmentLoad 3), 30 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed (both pinned rounding orders — component rollup and price pipeline — stated as pinned; both dual-variant pairs ASD/LRFD and PRELIMINARY/FINAL rendered at equal density), 0 missing
- validations[] conditions: 47 checked, 47 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 50 endpoints checked, all side-effect sets and every applies_to scope enumerated (existence codes §2.6, ERR_BUILDER_NOT_AUTHORIZED 5 ops §3.2, ERR_INVALID_STATE_TRANSITION 14 ops §2.5, ERR_CONFIGURATION_NOT_LOCKED 3 ops §3.4, ERR_ORDER_NOT_RELEASED 3 ops, ERR_INVALID_WINDOW_RANGE 2 ops), 0 missing
- entities[].fields[] structured content: 121 checked, all defaults / initial values / null-while-X semantics / range constraints reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups checked (APPROVE|REQUEST_REVISION, ASD|LRFD candidate lists, PRELIMINARY|FINAL, DRAFT→LOCKED|CRITERIA_STALE→LOCKED, lot complete|cancel, load dispatch|cancel, authorize|suspend), 7 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 823
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 matches `section-2.2-response-structure.md` byte-for-byte; all 30 state values, all enum values and all 47 error IDs appear verbatim in backticks; every error ID appears in §2/§3 narrative *and* the §5 table (none table-only); zero fuzzy/approximating words; zero operator or function-call syntax anywhere in the document; all 50 scaffold paths present in §4.

`SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Orchestrator anti-truncation verification (independent):** `wc -l` = 419, `wc -c` = 96806. §4 table = 52 pipe rows (header + separator + 50 endpoints). §5 table = 49 pipe rows (header + separator + 47 errors). Tail ends on a complete table row at a real section boundary. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T19:16:08.543Z

*(Steps 5 and 6 were launched concurrently in a single assistant message, per the skill's isolation requirement — the impl generator could not read `test_suite/` because the directory did not exist when it started. Both summaries are recorded below in numeric order; Step 6 actually finished first, at ~18:41Z, and Step 5 at ~19:15Z.)*

Test suite generation for task 2427 is complete.

## Files written

**`test_helpers/`** (Stage 1, 9 modules, 1,912 lines) — `__init__.py` (barrel), `api_client.py` (one method per endpoint, all returning raw responses), `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py` (single-step wrappers, BOM builders, six composite chains), `test_users.py` (8 roles + `make_builder_headers`), `types.py`.

**`test_suite/`** (Stage 2, `conftest.py` + 17 test files, 6,367 lines):
- Queue A (depth, §1.8): `test_01_design_variant_and_price_variant_arithmetic` … `test_09_compensating_ledgers` — **54 test functions** (58 collected cases; one parametrized rounding test expands to 5).
- Queue B (breadth, §1.9): `test_10_entity_creation_and_reads` (12), `test_11_lifecycle_transitions` (8), `test_12_derived_number_surfaces` (7), `test_13_input_validations` (6), `test_14_endpoint_contracts` (6), `test_15_error_catalogue` (9), `test_16_role_access_control` (7), `test_17_version_pinning_and_rollups` (6) — **61 test functions**.

**Total: 115 test functions / 119 collected cases.**

## Coverage audit

| Source | Instances | Non-stub | Translated |
|---|---|---|---|
| Difficulty (queue A) | 21 | 21 | **21/21** |
| Corner (queue B) | 85 | 55 | **55/55** |

Corner per section, all complete: entities 12, state_machines 8, calculations 4, validations 5, endpoints 5, errors 9, rbac 7, complexity_layers 4, consistency_model 1.

Mechanical gates, all green: `pyflakes test_suite/*.py` → EXIT=0; `pytest --collect-only` → 119 collected, no import errors; every test function has exactly one `Design:` line, it is the last line of the docstring, and all 115 tags resolve to a real non-stub instance in the correct section; no test carries a dual tag; zero occurrences of scaffold vocabulary in any test file. A dedicated citation checker confirmed every `PRD §x.y: "…"` block is a whitespace-normalised verbatim substring of `workspace/PRD.md` (**bad = 0** across all 17 files) — this caught and fixed 5 pre-existing fragment citations in `test_10`, `test_13` and `test_14`, which now quote the full §2.6 not-found sentence and the full §3.9 load-success sentence.

## Skipped / deliberately not asserted

- **30 corner instances marked `STUB excluded_because`** were not translated, per the skill's stub rule; each names the §1.8 instance that already covers it end to end (state_machines 6, calculations 8, validations 4, errors 10, complexity_layers 2). No placeholders, skips or xfails were emitted anywhere.
- **Three index expectations dropped for failing the PRD-first filter** (field/value named only in the design index, absent from the PRD, so not uniquely derivable):
  - `Quote.accepted_at` (index `errors` and `consistency_model`) — `accepted_at` appears zero times in the PRD; assertion removed.
  - `EngineeringDesign.approved_at` (index `rbac/the_submitting_engineer_must_not_review_their_own_design`) — `approved_at` appears zero times in the PRD and is absent from the §2.4 business-timestamp list; replaced with the PRD-derivable `reviewed_by_user_id` and `version` assertions from §3.6.
  - Quote terminal status `CONSUMED` (index `consistency_model`) — §3.5 states the terminal state is `ACCEPTED`; the test asserts `ACCEPTED`.

Nothing under `workspace/implementation/` was read or written at any point.

## Step 6: Generate implementation — 2026-09-02T19:16:08.543Z

Implementation complete and verified.

**Files written** — all under `/home/ubuntu/github/CodingPRD/tasks/task_2427_pre_engineered_metal_building_systems/workspace/implementation/`:
- `start.sh` (reads `$PORT`, guarded pip install, `exec python3 app.py`), `requirements.txt` (`Flask>=2.0`)
- `app.py` (blueprint registration + `ApiError`/`HTTPException`/`Exception` handlers, `strict_slashes = False`, binds 0.0.0.0)
- Core: `errors.py` (47-code catalogue → HTTP status), `constants.py` (enums + all Decimal rate/threshold constants), `store.py` (12 in-memory dicts, logical clock, `_seq` insertion counter, global `RLock`), `response.py` (meta/response_type/data envelope, pagination, Decimal→JSON), `middleware.py` (`roles_required` = bands 1–2 + lock), `validation.py` (typed field getters, band 3), `serializers.py` (12 explicit `*_out`)
- `services/calc.py` (11 pinned-rounding calculations), `services/domain.py` (lookups, `production_status_rollup`, `erection_sequence`, credit + shippable-pounds ledgers, both cascade chains)
- `routes/`: `jurisdictions, builders, configurations, quotes, designs, drawing_packages, orders, production, shipments, clock`

**Endpoint count: exactly 50** (verified by enumerating `app.url_map`).

**Notable design decisions**
- Precedence: PRD §3.8/§3.9 narrate check orders that contradict §2.5; I implemented the §2.5 15-band global precedence, confirmed against SCAFFOLD `validations[].priority` numbers, and annotated the conflict points in code (band 6 before band 10, band 8 before band 9).
- Storage in-memory only, empty on boot (confirmed: all 9 collections return `total_count: 0` on a fresh `start.sh`). Deterministic `created_at` ordering comes from a monotonic `_seq`, since the logical clock is frozen at `2026-08-01T00:00:00Z` and never falls back to wall time.
- Client-supplied datetimes are echoed verbatim under the public key with an aware `datetime` cached under a private `_..._dt` key; server-generated stamps use canonical 3-digit-fraction ISO+Z.
- Decimal + ROUND_HALF_UP throughout with the PRD's pinned rounding order (unit → line → sum for weights; per-cost whole-cent rounding before summing, volume tier keyed on the adjustment+freight-inclusive base).
- Order carries two independent dimensions: `engineering_status` set directly, `production_status` always re-derived by projection from lots/loads/holds; both conserved ledgers recomputed rather than incrementally patched, so cancels leave zero drift.
- Line windows: half-open with paint-colour changeover buffer; unload windows: closed intervals with per-`job_site_code` aggregate capacity across all builders' orders.

**Validation**: a 166-assertion smoke suite (`/tmp/pemb_smoke.py`, scratch, not part of the deliverable) passes 166/166 — auth bands, full happy path through seal/release/fabrication/dispatch, all hand-computed numerics (panel area 34470.00, wind 32.92 psf, estimate 99360, freight 274978, required moment 1199.06), both cascades including asymmetric non-resurrection of cancelled loads and voided designs, credit-ledger zero drift across accept/release/cancel-release, territory cap, quote expiry via clock moves, and pagination meta.

**Orchestrator note:** 22 implementation .py files / 2917 lines; 8279 lines across `test_suite/` + `test_helpers/`.

## Step 7: Run tests and iterate — 2026-09-02T19:37:41.273Z

All 8 parallel rounds are green (119/119 each, 0 failed / 0 errors / 0 skipped). The residual `pgrep` count was other pipelines' runners on the shared host, not this task's; `sweep.log` contains exactly 8 completion lines and all 8 `results.$i.json` were read off disk and parsed.

## Summary

**Iterations run:** 2 (iteration 1: 8/8 rounds at 110/119 with an identical, deterministic 9-test failure set — no flakiness, no `Terminated`/reaping artifact; iteration 2 after the fix batch: 8/8 rounds at 119/119).

**Tests deleted:** none. No failure traced to PRD silence — every one of the 9 was either an implementation defect or a test arithmetic error, each covered by a verbatim PRD sentence.

**Fixes to `test_helpers/`:** none. The triage hint did not apply: the failures did not share a setup error, and every fixture precondition traced correctly to PRD prose.

**Fixes to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2427_pre_engineered_metal_building_systems/test_suite/test_12_derived_number_surfaces.py` — `test_06_the_erection_projection_sorts_by_stage_then_by_creation_time`: corrected `blocked_load_count` from `3` to `2`. Its own fixture `_order_with_four_planned_trucks()` plans **two** `ANCHORAGE` trucks, both at `stage_sequence` 1, and PRD §3.9 defines `blocked_load_count` as the `PLANNED` loads *strictly greater* than the smallest `stage_sequence` among the `PLANNED` loads — so only the primary-frame (2) and secondary-frame (3) trucks count. Sibling `test_07` already asserts 2 for the same fixture; the test was internally inconsistent, not the implementation.

**Fixes to `implementation/`:**
- `workspace/implementation/store.py` — `wall_now()`: now returns `fmt_dt(db.logical_clock)` instead of `datetime.now(timezone.utc)`, so `created_at`/`updated_at` read the logical clock. PRD §2.4: "Time in this system is a **logical clock**, not wall-clock time … it never falls back to real time." Fixed 5 failures across `test_10`, `test_11`, `test_14`, `test_16`, `test_17`. Verified safe: `store.ordered()` sorts on the monotonic `_seq`, not on `created_at`, so collapsing many rows onto one timestamp cannot destabilize any `created_at`-ascending ordering.
- `workspace/implementation/services/domain.py` — `cascade_builder_suspension()`: also cancels the order's `SCHEDULED` lots when the order gains `commercial_hold`. PRD §3.8: "Separately, the system itself cancels a `SCHEDULED` lot when its order enters `permit_hold` or `commercial_hold`, as the cascades of §2.10 describe." (The `void_design_chain` permit-hold cascade already did this; the commercial branch did not.)
- `workspace/implementation/routes/orders.py` — `cancel_release()`: the band-9 from-state now admits `PROD_RELEASED`, `PROD_IN_FABRICATION` and `PROD_COMPLETE` before falling through to the band-10 active-work check. PRD §3.8 states in one paragraph both that the order "must be `PROD_RELEASED`, otherwise `ERR_INVALID_STATE_TRANSITION`" and, of the active-work refusal, to "note that a `COMPLETE` lot blocks cancellation just as a `SCHEDULED` one does" — but a `SCHEDULED`/`COMPLETE` lot always projects the order to `PROD_IN_FABRICATION`/`PROD_COMPLETE`, so under the literal reading that explicit note would be dead letter for lots. Admitting those two projections is the only reading under which both clauses are live (`PROD_NOT_RELEASED` and `PROD_HOLD` still yield `ERR_INVALID_STATE_TRANSITION`), and cancellation still only ever *succeeds* on an order with no active lot and no active load. I originally planned to relax the assertion to `validate_error_is_one_of([...])`; on closer reading the PRD does uniquely determine `ERR_ORDER_HAS_ACTIVE_WORK` here, so no assertion was weakened. `test_17::test_03` (version pin outranks the active-work test) still passes because the band-6 pin check is untouched and precedes it.

**Orchestrator independent verification** (per the standing caution that a Step 7 subagent can claim a clean sweep while leaving no artifacts behind): all 8 `results.*.json` exist on disk and parse to `passed == total == 119`; their mtimes are 19:34, which postdates every fix mtime (`store.py` 19:26, `services/domain.py` 19:26, `test_12` 19:26, `routes/orders.py` 19:29). The green sweep is genuine and post-fix, not a stale artifact from before the fix batch.

## Step 8: Finalize PRD — 2026-09-02T19:47:13.484Z

*(Not skipped: Step 7 applied 3 `implementation/` fixes and 1 `test_suite/` fix, so the skip condition — zero iterations beyond baseline — did not hold.)*

`PRD_FINALIZED.md` is written. 7 lines (paragraphs) touched, all traceable to `<step_7_diff>` items.

## Line counts
- `PRD.md`: 419 lines / 96,806 bytes
- `PRD_FINALIZED.md`: 419 lines / 98,287 bytes
- Line delta: 0 (+0.0%). Byte delta: +1,481 (+1.53%). 7 lines revised, 0 inserted, 0 deleted.

## Changes
- **§2.4 — revise** — after the business-timestamp list, added that `created_at`/`updated_at` also read the logical clock (not real time), that rows written without an intervening clock move share one instant and a backwards clock can stamp a later row earlier, that every `created_at` ascending ordering/tie-break in the document is realised as insertion order, and that `api_request_timestamp` alone is outside the logical clock — `implementation/store.py:54-62` (`wall_now`), used at `store.py:87` and `store.py:99`; ordering at `store.py:104-108`; exclusion at `response.py:26-28`.
- **§2.5 — revise** — band-9 list: cancel-release from-state widened from `PROD_RELEASED` to `PROD_RELEASED`, `PROD_IN_FABRICATION` or `PROD_COMPLETE` — `implementation/routes/orders.py:143-148`.
- **§2.10 (chain two) — revise** — added the lot hop: a commercial hold also cancels the order's `SCHEDULED` lots; "Three hops" → "Four hops" — `implementation/services/domain.py:214-217`.
- **§2.10 (asymmetry paragraph) — revise** — re-authorization resurrects neither the cancelled loads **nor** the cancelled lots — `implementation/services/domain.py:223-230` (clears `commercial_hold` + rollup only).
- **§3.2 (suspension) — revise** — dropped "three-hop", added the `SCHEDULED`-lot cancellation step and "every cascaded lot" to the version-increment list — `implementation/services/domain.py:198-220`, `routes/builders.py:115-119`.
- **§3.8 (cancelling a release) — revise** — from-state is now "a release still stands": `PROD_RELEASED`, `PROD_IN_FABRICATION` or `PROD_COMPLETE`; `PROD_NOT_RELEASED`/`PROD_HOLD` → `ERR_INVALID_STATE_TRANSITION`; kept the verbatim active-work sentences untouched — `implementation/routes/orders.py:143-156`.
- **§4 endpoint table (`/builders/{id}/suspend`) — revise** — "three-hop commercial-hold chain" → "commercial-hold chain of §2.10", for consistency with the new §2.10 hop count.
- **No edit** for the `test_suite/test_12` `blocked_load_count` 3→2 fix: PRD §3.9 already defines `blocked_load_count` verbatim as the `PLANNED` loads strictly greater than the smallest `PLANNED` `stage_sequence`, matching `domain.py:146-149`. Pure test arithmetic bug.

## Per-edit pre-edit search log

**Edit A (§2.4 audit stamps).** (a) Subject: source of `created_at`/`updated_at` and every ordering derived from them. (b) Enumerated: `grep -rn "wall_now|datetime.now|now_iso|utcnow|created_at"` over `implementation/` — `store.py:54` `wall_now` has exactly two callsites (`new_row:87`, `touch:99`); `now_iso` business stamps at `quotes.py`, `configurations.py:117`, `builders.py:98`, `drawing_packages.py:112`, `orders.py:114`, `production.py:166`, `shipments.py:182`; `response.py:27` `api_request_timestamp` uses real `datetime.now`; `grep -rn "\.sort(|sorted("` found exactly two sorts — `store.py:107` (`_seq`) and `domain.py:138` (`stage_sequence`, `_seq`); `response.py:89` `paginated` docstring assumes pre-sorted rows; `serializers.py:7`/`:145` (component rows carry `created_at` only); `routes/clock.py:13-19` `set_clock` accepts any instant with no monotonicity guard. (c) Two adjustments: (1) scoped the claim to the audit stamps and explicitly excluded `api_request_timestamp`, since `response.py:27` is genuinely wall-clock and an unqualified "all timestamps" would be a new mismatch; (2) after finding `clock.py` permits backwards moves, replaced the initial "rows that share a timestamp are ordered by insertion order" with the wider "that ordering is realised as **insertion order** … which is what `created_at` ascending means whenever the clock has only run forward", so the sentence also holds for the clock-rewind path (where `store.ordered` still returns `_seq` order while `created_at` is non-monotonic) and for §3.6's `created_at`-ascending component rollup and §3.9's `created_at` tie-break.

**Edit B (§2.10 chain two + asymmetry, §3.2, §4 table row).** (a) Subject: lot cancellation triggered by a hold flag, and what re-authorization restores. (b) Enumerated: `grep -rn "cascade_builder_suspension|cascade_builder_reauthorization|void_design_chain|commercial_hold|permit_hold"` — `domain.py:198-220` (suspension: loads → lots → weight ledger → rollup → touch order), `domain.py:161-178` `void_design_chain` (permit hold: cancels `SCHEDULED` lots but does **not** touch loads and does **not** recompute the pounds ledger), `domain.py:223-230` reauthorization (clears flag + rollup only — no lot or load revival), `domain.py:115-132` `production_status_rollup` (hold outranks lots, so the extra hop cannot change the projected `PROD_HOLD`), `routes/builders.py:107-120` suspend, `routes/orders.py:69-78` release paperwork gate, `routes/production.py` manual lot cancel, `serializers.py:192-193`. (c) Adjustment: phrased the new §2.10 hop as "exactly as a permit hold does, per §3.8 — every production lot of theirs with `status` `SCHEDULED` becomes `CANCELLED`" rather than folding lots and loads into one clause, because the permit chain cancels lots but **not** loads (`domain.py:170-177`); a symmetric phrasing would have wrongly implied the permit chain also cancels loads. Also widened the §2.10 asymmetry sentence to lots, since `cascade_builder_reauthorization` restores neither.

**Edit C (§2.5 band 9 + §3.8 cancel-release).** (a) Subject: the cancel-release from-state set and its interaction with the active-work band. (b) Enumerated: `routes/orders.py:121-175` (band 6 version pin at :130 precedes the band-9 from-state at :143, which precedes the band-10 lot/load scan at :151-156); `domain.py:115-132` `production_status_rollup` to confirm which of the five projections are reachable and that `PROD_HOLD`/`PROD_NOT_RELEASED` remain refused; `routes/orders.py:44-118` `release_to_fabrication` (its own band-9 `PROD_NOT_RELEASED` check is untouched, so the §2.5 sentence's first half stays verbatim); §4 table row for `/orders/{id}/cancel-release` ("only possible while no lot or load is active" — still accurate, left verbatim); cross-checked `test_suite/test_14_endpoint_contracts.py:313-359` and `test_suite/test_17_version_pinning_and_rollups.py:162-192` for the surviving `ERR_ORDER_HAS_ACTIVE_WORK` and version-pin-outranks expectations. (c) Adjustment: kept the entire verbatim active-work paragraph (including the `COMPLETE`-lot and `DISPATCHED`-load notes) untouched and added only the from-state clause plus a one-sentence rationale, so the edit widens the from-state without weakening the `ERR_ORDER_HAS_ACTIVE_WORK` guarantee — cancellation still only ever succeeds on an order with no active lot and no active load.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` yields 14 changed lines (7 revised paragraphs), line count unchanged at 419, tail intact through the final error-catalogue row.

## Step 9: Complete PRD — 2026-09-02T19:57:31.454Z

Done. Verified integrity: `PRD_COMPLETED.md` is still 419 lines, ends at `` `ERR_BUILDER_CREDIT_EXCEEDED` | 402 Payment Required ``, §4 still has 50 endpoint rows, §5 still has 47 error rows. A field-by-field sweep confirms every response key the implementation emits is now named in the PRD.

## Counts

- Source `PRD_FINALIZED.md`: 419 lines / 98,287 chars → `PRD_COMPLETED.md`: 419 lines / 102,165 chars (**+3,878 chars**, no line-count change — all edits are in-paragraph)
- **16 ambiguity-pins**, **6 mismatch-revisions**

## Changes

- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; empty-string param falls back to default — `response.py:68-86`
- §2.5 (band 3) — revise — ambiguity — `component_marks` entries must be non-empty strings, not merely strings — `validation.py:136-141`
- §2.5 (band 9) — revise — **mismatch** — "fourteen operations" → "sixteen"; added builder authorize (`PENDING_AUTHORIZATION`/`SUSPENDED`) and suspend (`AUTHORIZED`) from-states, which the enumeration omitted entirely — `builders.py:84-85, 112-113`
- §2.10 — revise — ambiguity — re-authorization clears `commercial_hold` only on orders that carry it; others not rewritten — `domain.py:225-230`
- §3.1 — insert — ambiguity — jurisdiction `name` must be non-empty — `jurisdictions.py:35`
- §3.1 — insert — ambiguity — `authorized_builder_count` is derived at read time; a headcount change never bumps the jurisdiction's `updated_at`/`version` — `serializers.py:15-31`
- §3.2 — insert — ambiguity — builder `name` must be non-empty — `builders.py:30`
- §3.2 — insert — ambiguity — only orders currently holding `commercial_hold` are recomputed/version-bumped; authorize-from-`AUTHORIZED` and suspend-from-non-`AUTHORIZED` yield `ERR_INVALID_STATE_TRANSITION` — `domain.py:225-230`, `builders.py:84,112`
- §3.3 — insert — ambiguity — `building_length_ft` and `footprint_sqft` are stored as exact unrounded products (§2.7's 2-dp area rule does not apply), and the exact footprint feeds roof panel area and frame-weight estimate — `calc.py:41-46, 73`
- §3.4 — insert — ambiguity — kit attachment is gated on nothing but configuration existence (any status, builder need not be authorized) and does not touch the configuration's `updated_at`/`version` — `configurations.py:123-149`
- §3.4 — insert — ambiguity — the adjustment floor is tested only at quote creation, never re-tested under the `FINAL` variant — `orders.py:88-103`
- §3.5 — insert — ambiguity — `requested_erection_start_date` must be a parseable ISO 8601 string and is echoed verbatim — `quotes.py:124-126, 162`
- §3.6 — insert — ambiguity — an explicitly-null field counts as absent on both halves of the component class split; the stored component carries the full field set with inapplicable fields null — `validation.py:20-21`, `designs.py:97-114`, `serializers.py:144-162`
- §3.7 — revise — **mismatch** — PRD said a package is opened "against an approved design"; impl applies no design-status gate at open, enforcing approval only at seal — `drawing_packages.py:16-43`
- §3.8 — insert — ambiguity — line `code` has no character-set restriction and is checked for uniqueness only against other lines; line `name` non-empty — `production.py:23-36`
- §3.8 — revise — **mismatch** — release conditions reordered to the actual band order: version pin, then builder authorization, then `PROD_NOT_RELEASED` from-state (PRD listed from-state first) — `orders.py:52-66`
- §3.8 — insert — **mismatch** — cancel-release version pin is a band-6 check evaluated *before* the from-state — `orders.py:129-148`
- §3.8 — insert — ambiguity — lot `window_start`/`window_end` echoed verbatim as supplied — `production.py:64-65, 111-112`
- §3.9 — insert — ambiguity — `carrier_name` non-empty; unload window bounds echoed verbatim — `shipments.py:34, 37-38, 104-105`
- §3.9 — revise — **mismatch** — version pin is checked *first*, before the order's `production_status` (PRD had production status first) — `shipments.py:43-53`
- §3.9 — revise — **mismatch** — the `ERR_INVALID_WINDOW_RANGE` check (band 13) precedes `ERR_DUPLICATE_MARK`/`ERR_MARK_ALREADY_ASSIGNED`/capacity (band 14); PRD's narrative had it last — `shipments.py:72-93`
- §5 — insert — ambiguity — an unmatched path answers `ERR_INVALID_REQUEST` at 404 and an unsupported method at 405, without consulting auth headers — `app.py:53-68`

Notable finding worth flagging: the two most substantive divergences were the **drawing-package open gate** (PRD prose promised an approved-design requirement the implementation never enforces) and the **`ERR_INVALID_STATE_TRANSITION` operation count** (§2.5 enumerated exactly fourteen from-states but the implementation guards sixteen, the two extras being builder authorize/suspend — a state machine the PRD described narratively without ever naming its failure code).

**Orchestrator verification:** `PRD_COMPLETED.md` = 419 lines / 102,165 chars; §4 table 52 pipe rows (50 endpoints), §5 table 49 pipe rows (47 errors), tail ends on the `ERR_BUILDER_CREDIT_EXCEEDED` row. No truncation.

---

## Pipeline complete — 2026-09-02T19:57:31.454Z

All nine steps ran to completion. Final state:
- `SCAFFOLD.yaml` + `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (21 instances) + `SCAFFOLD_CORNER_DESIGN.yaml` (55 non-stub instances) — clean scaffold lint.
- `workspace/PRD.md` (419 lines) → `PRD_FINALIZED.md` (7 paragraphs revised) → `PRD_COMPLETED.md` (16 ambiguity-pins + 6 mismatch-revisions).
- `test_helpers/` (9 modules) + `test_suite/` (17 files, 115 test functions / 119 collected cases); all 21 difficulty and all 55 non-stub corner instances translated.
- `workspace/implementation/` — Python + Flask, 50 endpoints, in-memory only, no seeded data.
- **Final sweep: 8/8 parallel rounds green at 119/119**, results.1–8.json on disk, mtimes postdating every fix.
- Zero tests deleted and zero assertions weakened across the whole pipeline — every Step 7 failure resolved as a genuine implementation defect (3) or an internally inconsistent test computation (1).
