# Worklog — task_2448_vehicle_service_information_repair_data_access

## Step 1: Create task directory — 2026-09-02T19:46:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2448_vehicle_service_information_repair_data_access` and its `workspace/` subdirectory. Index 2448 was pre-assigned by the orchestrating pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-02T21:17:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2448_vehicle_service_information_repair_data_access/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2448_vehicle_service_information_repair_data_access/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2448_vehicle_service_information_repair_data_access/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  984

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

`/home/ubuntu/github/CodingPRD/tasks/task_2448_vehicle_service_information_repair_data_access/`

**SCAFFOLD.yaml** (2447 lines, §1.0–§1.7; contains neither design key) — domain `vehicle-service-information-access`, archetype `access_control_matrix` + `compliance_audit`, `difficulty_level: expert_plus`, entity topology `graph`, state-machine shape `parallel`, role model `segregation_of_duties`, consistency `immediate`. Counts: **14 entities, 7 state machines, 2 concurrency rules, 6 calculations, 37 ordered validations, 53 endpoints, 37 errors, 5 roles**. Core entities: Manufacturer, VehicleModel, SystemArea, License, Shop, Technician, ShopEntitlement, SeatAssignment, DiagnosticTool, Publication, PublicationVersion, GatewaySession, ModuleProgrammingJob, AuditEvent.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1663 lines) — 9 rule ids × 2 instances = 18: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

**SCAFFOLD_CORNER_DESIGN.yaml** (4445 lines) — all 9 sections, **68 instances (57 with test recipes + 11 `excluded_because` stubs)**: entities 12, state_machines 10+4, calculations 7+3, validations 5+2, endpoints 6, errors 7, rbac 6, cross_cutting_complexity_layers 3+2, consistency_model 1. Claim types are one-per-row from the extraction guide (no duplicates except deliberate pairs).

## Verification performed beyond lint

- Setup-chain replay: scripted call-by-call ordering audit over all 75 recipes (clock first, funding before entitlement, license ACTIVE before entitlement, verify before session activate, seat+tool before session, session ACTIVE before job, mint before publish) — 0 issues; plus manual end-state replay of every money/counter literal against the formulas (entitlement_charge PRO 85000 / ENTERPRISE 70000 / seat-boundary 100000 vs 105000; gateway fees 7276, 11016, 5742, 2912; parity 1.1500 COMPLIANT; coverage 0.00/50.00/100.00).
- 454 asserts audited for exact field names and enum literals against §1.1; 37/37 errors referenced; all 53 endpoints exercised by at least one structured call; 86 instance names unique across both files; all 11 stub citations resolve to real §1.8 instance names; grounds all resolve; no forbidden concurrency vocabulary in any file.

## Adjudications / fixes made

1. **YAML-breaking `?` convention**: the skill's own `input: [field?]` optional marker is rejected by PyYAML inside flow sequences, so the lint could not parse SCAFFOLD.yaml at all. Quoted the 17 affected `input:` lines (`"basis?"`, `"limit?"`, …), preserving the marker string exactly. Worth flagging upstream — any scaffold following the template literally will hit this.
2. Wrong enum literal in one assert: `settlement_status == PROVISIONAL` → `UNSETTLED` (the declared enum is `UNSETTLED | SETTLED`).
3. `complexity_profile.difficulty_level_note` said "52 endpoints"; actual is 53 — corrected.
4. Enum closure gap: `License.license_model: EITHER` had no defined meaning. Priority 61's check now spells out `permitted(SUBSCRIPTION)={SUBSCRIPTION}`, `permitted(PER_VEHICLE)={PER_VEHICLE}`, `permitted(EITHER)={SUBSCRIPTION, PER_VEHICLE}`.
5. Endpoint-coverage gaps: `GET /manufacturers/{id}/vehicle-models`, `GET /gateway-sessions`, `GET /programming-jobs` were never called; added them (with asserts) to three existing §1.9 instances rather than inventing filler instances.
6. Normalized 68 §1.9 grounds pointers to the §1.8 notation (`validations[priority=N]`, `errors[ERR_X]`, `entities.X.fields.y`).
7. Design calls: excluded `POST /publications/{id}/versions` from the typed-404 sweep (its required OCC input cannot be a literal under contract 3c); used negative name markers (`_cannot_`, `_returns_4XX`, `_rejected`, `_not_found`, `_unauthorized`, `_input_ignored`) on instances that intentionally violate role/input schemas; kept every `expected_*_version` a captured `${var}`.

The sibling-task prohibition was respected throughout — no read, glob, or grep touched any `tasks/task_*` directory other than task 2448's own.

## Step 3: Copy shared files — 2026-09-02T21:18:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T21:32:00.000Z

PRD generated and verified complete.

**Output:** `workspace/PRD.md` — **409 lines**, last heading **`## 5. Error Code Catalogue`**, file ends at the final error-table row (`ERR_INSUFFICIENT_DATA_CREDIT | 402`). No audit footer, no truncation.

**Section list**
- §1 Introduction (3 paragraphs — right-to-repair pricing parity + data availability framing)
- §2 Global Specifications: 2.1 Operators, Roles and Secure-Gateway Identity / 2.2 API Response Structure (verbatim, diff-verified byte-identical to `section-2.2-response-structure.md`) / 2.3 Pagination / 2.4 Resource Identity, Revision Counters and Timestamps / 2.5 Stale-Revision Protection on Seat and Version Writes / 2.6 Reference Resolution and Path Traversal Order / 2.7 The Order in Which Requests Are Refused / 2.8 Money, Ratios and Rounding Discipline / 2.9 The Logical Clock and Interval Conventions / 2.10 Cascade Propagation and the Audit Trail
- §3 Business Logic (9 subsections): 3.1 OEM Catalogue & Pricing-Parity Verdict / 3.2 Licensing / 3.3 Shops, Data Credit & Entitlement Purchase / 3.4 Activation, Settlement & the Two Exit Branches / 3.5 Technician Identity, Seats & Suspension Cascade / 3.6 Publication Pipeline / 3.7 Gateway Sessions, Tool Occupation & Access Pricing / 3.8 Programming Jobs & Version Pinning / 3.9 Coverage Completeness, Gap Identification & Audit Trail
- §4 Endpoint Definitions (4-column table) · §5 Error Code Catalogue (2-column table)

**Coverage vs scaffold** — 53/53 endpoints in §4, 37/37 errors in §5 and all 37 referenced in §2/§3 prose, 37/37 validations (priority ladder stated explicitly in §2.7 with all 16 rungs), 32/32 state transitions across all 7 machines (incl. both `PublicationVersion` parallel axes and all system-cascade transitions), 6/6 calculations with pinned rounding order and all constants embedded (TIER_MULT/SEAT_STEP/INCLUDED_SEATS, PARITY_MAX_INDEX 1.15, DAYS_PER_MONTH 30, SESSION_BASE 2500, VIN_CREDENTIAL 300, JOB_CENTS, both discount tiers, both surcharge rates, COOLDOWN 24h), 2/2 OCC rules, both conserved-quantity invariants (seat + data-credit).

**Hard Contracts**

```
Field coverage check:
- entities[].fields: 87 required, 87 present, 0 missing
- endpoints[].request_body: 53 required, 53 present, 0 missing
- endpoints[].query_params: 23 required, 23 present, 0 missing
- errors[].id: 37 required, 37 present, 0 missing
- roles[].name: 5 required, 5 present, 0 missing
- state enumeration values: all present, 0 missing
Status: PASS
```
(two passes; `publication_id` was missing on pass 1 and was added to §3.6)

```
Rule coverage check:
- validations[] with priority: 37 checked, 37 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 32 checked, 32 fully expressed, 0 missing
- calculations[]: 6 checked, 6 fully expressed, 0 missing
- validations[] conditions: 37 checked, 37 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 53 checked, 53 expressed, 0 missing
- entities[].fields[] structured content: 87 checked, 87 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (license activate DRAFT/SUSPENDED, technician suspend VERIFIED/UNVERIFIED, entitlement CANCELLED/LAPSED, session COMPLETED/EXPIRED/TERMINATED, job abort from 3 states, parity LIST/EFFECTIVE, coverage EFFECTIVE/DECLARED, charge PROVISIONAL/FINAL x SUBSCRIPTION/PER_VEHICLE), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 818
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also scanned clean for fuzzy/approximating words (one "roughly" found and rewritten precisely) and for pseudocode operator syntax (`>=`, `==`, `+=`, etc. — zero occurrences). The two design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no sibling task was read.

**One judgement call to flag:** the scaffold declares entitlement window bounds relative to the license (`window_start` at or after `License.effective_start`, `window_end` at or before `License.effective_end`) as field constraints but nominates no error id for them. I attached them to `ERR_INVALID_REQUEST` (the declared-bounds rung) so the implementer gets a determinate answer; if the hidden tests expect these to be unchecked, that sentence in §3.3 is the one to revisit.

**Orchestrator truncation check (per pipeline instruction):** independently verified — 409 lines, 27 headings ending at `## 5. Error Code Catalogue`, tail is a complete markdown table row. Ends at a real section boundary. No regeneration needed.

## Step 6: Generate implementation — 2026-09-02T22:12:00.000Z

Implementation is complete and verified.

## Files written
All under `workspace/implementation/` (2,946 lines of Python):

- `start.sh` (executable, cwd-independent, guarded `pip install`, `exec python3 app.py`), `requirements.txt` (`Flask==3.0.3`)
- `app.py` — `create_app()`, `ApiError`/`HTTPException`/catch-all handlers, `app.run(host=0.0.0.0, port=$PORT|10000, threaded=True)`
- Core: `store.py` (in-memory dicts + logical clock), `errors.py` (37 error ids → status map), `envelope.py` (meta/response_type/data), `auth.py` (header auth, shop scope, seat-holder), `validate.py` (shape + pagination + query parsing), `calc.py` (parity, entitlement charge, gateway fee, coverage), `serialize.py` (per-entity field projection), `services.py` (audit append, pin counts, session pricing/close, cascade hops)
- `routes/`: `common.py`, `catalogue.py` (8), `licenses.py` (4), `shops.py` (11), `entitlements.py` (9), `publications.py` (8), `sessions.py` (11), `misc.py` (2), `__init__.py`

## Endpoint count
**53 implemented / 53 declared in PRD §4** — confirmed by enumerating `app.url_map` (list matches the §4 table exactly, no extras).

## Verification
Two smoke suites (~130 assertions) against freshly booted servers; both pass. Every PRD worked example reproduces exactly:
- Parity: list 1.1500 COMPLIANT vs effective 1.5333 NON_COMPLIANT on the same row; restatement to 115,100 → 1.1510 NON_COMPLIANT
- SUBSCRIPTION provisional 84,999 (per-line rounding, not 85,000); day-11 cancel → settled 27,419, refund 57,580, balance 172,581, funded total unchanged
- PER_VEHICLE 40 × 2,500 × 0.85 = 85,000
- Gateway fee 9,800 / discount 490 / surcharge 1,176 / total 10,486, accrued on shop, tool released
- Coverage 0.00 EFFECTIVE vs 50.00 DECLARED on the two-cell GAP+DEGRADED shape, gaps ordered by `model_code` then area `code`; stored pct tracks the effective basis
- Cascades: publish-supersede and recall → `REVALIDATION_REQUIRED` + pin decrement, repin, session `COMPLETED` vs `EXPIRED` fork, license termination hops 1–3, credit conservation identity

Fresh-boot cleanliness confirmed: a newly launched process reports `total_count: 0` on `/audit-events`; no seeding, no SQLite, no disk or `/tmp` writes (grep-verified). Background servers were stopped; no processes remain.

## Interpretation decisions
1. **`LICENSE_TERMINATED` actor** — §3.3 ends "every audit row in this cascade … carries `actor_role` of `SYSTEM`", but §2.4 defines `SYSTEM` as "when the row was produced by a cascade rather than by a direct call", and the SCAFFOLD annotates `SYSTEM` on the hop rows only. I record the license's own row with the acting `PlatformAdmin` and all three hop rows (`ENTITLEMENT_SETTLED`, `SEAT_REVOKED`, `SESSION_TERMINATED`, plus `JOB_ABORTED`) as `SYSTEM`/null. This is the one place the two PRD sentences pull apart.
2. **Uniqueness breaches** (`oem_code`, SystemArea `code`, `model_code` per model-year, `serial_no` per shop) have no dedicated error id → `ERR_INVALID_REQUEST` (400).
3. **Reference-miss error ids**: `POST /vehicle-models` manufacturer miss → `ERR_REFERENCED_RESOURCE_NOT_FOUND` (§2.6 secondary list) while `POST /licenses` uses `ERR_MANUFACTURER_NOT_FOUND`.
4. **Scope-check placement**: for payload-`shop_id` endpoints only `shop_id` presence/type is validated before the 403; for row-derived scope (entitlement/seat/session) the row is loaded first, then scope, then full shape — matching the §2.7 rung order.
5. **Job queueing has no session-state gate** (the PRD declares one only at start/complete/repin); the ADAS calibration gate sits between credential expiry and stale-pin in the start ladder, exactly as §3.7 orders it.
6. **EXPIRED sessions** leave `termination_reason` null (the PRD stamps it only on the cascade `TERMINATED` exit) and audit as `SESSION_TERMINATED` with `detail=reason=SESSION_EXPIRED`.
7. **Datetimes are echoed verbatim**; parsed copies live under `_`-prefixed keys that the serializer never emits.

## Step 5: Generate unit tests — 2026-09-02T23:02:00.000Z

Done. The citation pass is finished and the suite audits clean.

## Files written

**`test_helpers/` (9 files, ~3,150 lines)** — `__init__.py`, `api_client.py` (all 40+ endpoints), `api_errors.py` (`ApiErrorId`, `ERROR_HTTP_STATUS`, `NOT_FOUND_PRECEDENCE`), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py` (scenario builders + composites), `test_users.py`, `types.py`.

**`test_suite/` (conftest + 15 modules, 95 tests)** — `test_01`–`test_06` carry queue A; `test_07`–`test_15` carry queue B:

| module | tests | module | tests |
|---|---|---|---|
| test_01 pricing/parity/license activation | 6 | test_09 identity/session/version transitions | 5 |
| test_02 entitlement charge & credit ledger | 8 | test_10 pricing inputs, constants, bases | 7 |
| test_03 seat ledger & entitlement windows | 5 | test_11 validation gates & boundaries | 5 |
| test_04 gateway fee & activation gates | 6 | test_12 endpoint contracts & computed reads | 6 |
| test_05 publication axes & programming jobs | 6 | test_13 typed errors & error refinements | 7 |
| test_06 cascades & coverage map | 6 | test_14 role authority & scope isolation | 6 |
| test_07 resource shape/defaults/lookup | 12 | test_15 concurrency guards & derived reconciliation | 5 |
| test_08 license & entitlement lifecycles | 5 | | |

## Counts

- **Queue A (Difficulty): 37 tests / 18 non-stub instances** — every instance has >=2 tagged tests.
- **Queue B (Corner): 58 tests / 57 non-stub instances** — every instance has >=1 tagged test.
- **Total 95 tests, 95 `Design:` tags**, one per test, zero untagged, zero dual-tagged, zero tags resolving to a nonexistent or stubbed instance (verified by an AST+YAML audit).

## Instances translated vs skipped

- **75 / 75 non-stub instances translated. Zero skipped** — no instance failed the PRD-first two-condition filter, so there are no gaps to report.
- **11 corner instances not translated because they are `excluded_because:` stubs** (all deferring to a queue A difficulty instance that already covers the behaviour): `state_machines/publication_version_parallel_axis_independence`, `state_machines/programming_job_cyclic_revalidation_loop`, `state_machines/license_terminate_cascade_down_to_seats_and_sessions`, `state_machines/license_activation_guarded_by_manufacturer_parity_state`, `calculations/entitlement_charge_variant_selection_by_lifecycle_position`, `calculations/entitlement_charge_reconciliation_delta_credited_on_settlement`, `calculations/parity_index_threshold_crossing_at_parity_max_index`, `validations/seat_cap_outranks_insufficient_credit_priority_ordering`, `validations/tool_window_temporal_conflict_detection`, `cross_cutting_complexity_layers/cascading_side_effects_three_level_chain_end_to_end`, `cross_cutting_complexity_layers/dual_variant_calculation_both_variants_and_switch_delta`.

## Final checks

- **PRD-citation pass complete.** 214 quoted docstring fragments checked against `workspace/PRD.md`; 6 paraphrases-presented-as-quotes were found and replaced with verbatim text (test_02 refund sentence, test_04 half-open overlap, test_06 stored coverage figure, test_07 x4: technician defaults, typed 404, `manufacturer_id` secondary reference, pagination meta, plus two in test_15). The only remaining checker flags are known false positives: ellipsis-elided quotes whose halves each verify individually, quotes closed with a period where the PRD sentence continues with a dash/comma, and one regex artifact that pairs two adjacent quotes in test_02.
- No `skip`, `skipif`, or `xfail` anywhere in `test_suite/`; `python3 -m py_compile` passes over all 16 suite files and all 9 helper files.
- The implementation directory was never read, and no sibling `task_*/` directory was accessed.

## Step 7: Run tests and iterate — 2026-09-02T23:35:00.000Z

All 8 rounds green. The "Terminated" grep hits were just the test-name `TestTerminatedLicenseIsTerminal`, not a reaped-sweep signal (no server log ended in `Terminated`, and no round died early).

## Summary

**Iterations run:** 2 (one 8-round parallel sweep to find the defect, one to confirm the fix).

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence, so no PRD-silence or unique-derivability collapse applied.

**Fixes applied to `test_helpers/`:** none — the fixture/factory layer was consistent with PRD throughout.

**Fixes applied to `implementation/`:** none. The single failure was a test mis-translation, and the implementation's behaviour is what PRD §2.6 verbatim requires.

**Fix applied to `test_suite/`:**
- `test_suite/test_07_resource_shape_defaults_and_lookup.py` — `TestTypedLookupsAndNavigation::test_a_vehicle_model_under_an_unknown_manufacturer_is_a_typed_404` (renamed to `..._is_a_secondary_404`). It asserted `ERR_MANUFACTURER_NOT_FOUND` on `POST /vehicle-models` with an unresolvable `manufacturer_id`; the implementation correctly returns `ERR_REFERENCED_RESOURCE_NOT_FOUND`.

**Why the test was wrong (STEP 2, assertion mis-translation):** PRD §2.6 enumerates this exact case in the *secondary*-reference list — "…the `manufacturer_id` axis check when a vehicle model is registered … all of these resolve to `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404) when they fail." The test's own docstring conceded that placement and then overrode it by leaning on the unrelated sentence about the ten typed not-found errors ("the same error is used whether the missing identifier arrived in the path or in the request body"), which governs *which* typed error a primary reference uses, not whether this reference is primary. The specific enumeration is the governing prose, so the exact-error assertion was corrected (not weakened — it remains an exact `error_id` + status check), and the docstring now quotes the §2.6 secondary sentence.

**Final sweep evidence** (`workspace/implementation/results.{1..8}.json`, all complete JSON):

| round | passed/total |
|---|---|
| 1 | 95/95 |
| 2 | 95/95 |
| 3 | 95/95 |
| 4 | 95/95 |
| 5 | 95/95 |
| 6 | 95/95 |
| 7 | 95/95 |
| 8 | 95/95 |

failed = 0 and errors = 0 in every round. The prior sweep was 94/95 in all 8 rounds with the identical single failure, confirming the defect was deterministic rather than load-induced and that the fix is not masking flakiness.

**Orchestrator independent verification:** re-read all 8 `results.*.json` directly — every file reports `passed=95 failed=0 errors=0 total=95 skipped=0`; timestamps cluster at 23:11, all 8 files present. `grep` for `xfail` / `mark.skip` / `pytest.skip` across `test_suite/` and `test_helpers/` returns 0 hits, and the suite still contains 95 `def test_` functions (no silent deletions). Sweep result accepted.

**Step 8 gate:** the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is NOT met — there was 1 `test_suite/` fix, which surfaced a genuine PRD tension between the §2.6 secondary-reference enumeration and the typed-not-found sentence. Step 8 therefore runs, with that item as its focus list.

## Step 8: Finalize PRD — 2026-09-02T23:23:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one edit.

## Line counts
- PRD.md: 409 lines; PRD_FINALIZED.md: 409 lines. **0.00% line delta** (one line revised in place, +1 sentence).

## Change
- **§2.6 (Reference Resolution and Path Traversal Order)** — *revise* — appended a disambiguating clause to the secondary-reference paragraph: the secondary enumeration governs over the earlier "same error whether path or body" remark where they collide, so `POST /vehicle-models` with an unresolvable `manufacturer_id` answers `ERR_REFERENCED_RESOURCE_NOT_FOUND` (not `ERR_MANUFACTURER_NOT_FOUND`), while `manufacturer_id` in a license draft stays a primary reference answering `ERR_MANUFACTURER_NOT_FOUND` — `implementation/routes/catalogue.py:162-163` and `implementation/routes/licenses.py:53`.

## Pre-edit search log (mandatory per edit)
**Edit 1 — §2.6 primary-vs-secondary resolution of `manufacturer_id`**
- (a) Subject: which typed 404 a `manufacturer_id` (and, by extension, any ten-list entity identifier) yields when it fails to resolve, and whether path-vs-body placement decides it.
- (b) Paths enumerated (grepped `NOT_FOUND` across all of `implementation/`, then read each site):
  - `routes/catalogue.py:157-163` — `POST /vehicle-models`, body `manufacturer_id` → `ERR_REFERENCED_RESOURCE_NOT_FOUND` (the Step 7 site; ref check runs *after* `get_int`/`get_str` shape checks, consistent with rung 6 → 8).
  - `routes/catalogue.py:88, 102, 114, 141, 188` — all five path-borne `manufacturer_id` endpoints (read, pricing restate, parity report, license list, model list) → `ERR_MANUFACTURER_NOT_FOUND`.
  - `routes/licenses.py:53` — `POST /licenses`, **body** `manufacturer_id` → `ERR_MANUFACTURER_NOT_FOUND`; `licenses.py:85-90` — activation re-resolves `covered_system_area_ids` → secondary.
  - `routes/publications.py:41-43` — body `vehicle_model_id`/`system_area_id` → secondary (neither entity is in the ten-list, so no collision).
  - `routes/sessions.py:76` — body `diagnostic_tool_id` → secondary; `sessions.py:398-407` — re-pin replacement version resolved primary (`ERR_PUBLICATION_VERSION_NOT_FOUND`) first, then secondary only for the wrong-publication case.
  - `routes/entitlements.py:70-71, 215-216`, `routes/shops.py` — all other body-borne ten-list references (`shop_id`, `license_id`, `technician_id`, `entitlement_id`, `seat_assignment_id`, `session_id`) → their own primary typed 404s.
  - Conclusion from the sweep: vehicle-model registration is the **only** place in the whole implementation where a ten-list entity referenced from a body resolves to `ERR_REFERENCED_RESOURCE_NOT_FOUND`.
- (c) Wording adjustment: my first draft would have generalised ("a `manufacturer_id` in a payload is a secondary reference"), which `licenses.py:53` contradicts. I re-scoped the sentence to the single enumerated case and added the explicit license-draft counter-example, and phrased the precedence as "wherever the two could be read against each other" so the sentence neither promotes nor demotes any other reference site. The pre-existing §2.6/§2.7 prose about the ten typed errors, their precedence order, and rung ordering is untouched and remains verbatim.

Note on scope: the sole `<step_7_diff>` item was a `test_suite/` docstring+assertion correction with no implementation change, and Step 7 judged PRD §2.6 verbatim sufficient. I still made this one edit because the same §2.6 contains a second sentence that a careful reader (and the Step 7 test author) resolved the opposite way; the edit only makes the existing governing reading explicit and adds no new behavior.

## Step 9: Complete PRD — 2026-09-02T23:39:00.000Z

Done. Verified all 53 endpoints, both cascade families, all calculation formulas, and the error ladder against the PRD.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 409 lines / 90,411 chars → `PRD_COMPLETED.md` 409 lines / 97,326 chars (**+6,915 chars**, line count unchanged — every change is an in-paragraph insert or revision; no new sections or paragraphs).

**Counts:** 27 ambiguity-pins, 4 mismatch-revisions (31 edits across 29 lines).

### Mismatch revisions
- §3.5 (technician suspension, hops 3–4) — revise — mismatch — hop 3 aborts `REVALIDATION_REQUIRED` jobs too, and hop 4 decrements `active_pin_count` only for jobs that left `QUEUED`/`IN_PROGRESS` — services.py:239-240 via routes/shops.py:186
- §3.5 (explicit seat revoke) — revise — mismatch — residual-job abort set is `QUEUED`/`IN_PROGRESS`/`REVALIDATION_REQUIRED` with selective pin decrement, not "each aborted job" — services.py:236-243
- §3.4 (cancellation side-effects) — revise — mismatch — entitlement `version` advances by 1 for the settlement **plus** 1 per seat the cascade revokes (seat-ledger recompute touches the entitlement) — services.py:208-209 + services.py:261
- §3.4 (lapse divergences) — revise — mismatch — "the same `version` advance by 1" → "the same pattern of `version` advances" — services.py:250-261

### Ambiguity pins
- §2.2 — insert — `api_request_id` is `req_` + 20 uppercase-alnum chars — envelope.py:14
- §2.2 — insert — `api_request_timestamp` is the one timestamp read from the host wall clock, not the logical clock — envelope.py:19-20
- §2.3 — insert — `created_at` ties (and audit `occurred_at`/`created_at` ties) break on insertion order — services.py:38, routes/misc.py:33
- §2.4 — insert — `created_at`/`updated_at` read the logical clock — store.py:95-103
- §2.4 — insert — client-supplied instants stored/echoed verbatim, not re-rendered — routes/licenses.py:68-69
- §2.5 — insert — `expected_*_version` below 1 is a shape error (rung 6), not a stale one — routes/entitlements.py:212
- §2.7 — insert — when a scope/seat-holder/SoD check must load a row first, the rest of the shape pass and all other reference resolution defer with it — routes/sessions.py:51-63, routes/publications.py:165-172
- §2.7 — insert — declared-unique collisions answer `ERR_INVALID_REQUEST` after references resolve; the seven bodiless action endpoints accept no field at all; unbounded free-text fields must be non-empty with no max — routes/catalogue.py:45-47, routes/licenses.py:81, validate.py:33
- §2.9 — insert — clock reply echoes the supplied instant verbatim; may move backward — routes/misc.py:42-44
- §2.10 — insert — full `detail` convention table (`vin=`, `job_type=`, `reason=` on six event types, null on seven) — services.py:129-131, 216, 232
- §3.1 — insert — `requires_security_credential` drives no enforced gate — (never read anywhere in impl)
- §3.1 — insert — `region` is report-only; ceiling is 1.15 in every region — calc.py:16
- §3.1 — insert — a restatement supplying none of the four figures is accepted and still advances `version` — routes/catalogue.py:98-106
- §3.1 — insert — the two normalised figures are rounded half up to 4 dp and reported on either basis — routes/catalogue.py:127-130
- §3.3 — insert — `amount_cents` >= 1; `funding_ref` required non-empty but persisted nowhere — routes/shops.py:64-65
- §3.3 — insert — window-bounds comparison follows the license lookup, so `ERR_LICENSE_NOT_FOUND` wins — routes/entitlements.py:71-78
- §3.3 — insert — per-vehicle provisional charge excludes the seat factor; `vin_quota` is a pricing input never enforced as a cap — calc.py:117
- §3.4 — insert — cancellation `reason` is required but recorded nowhere (not on the row, not in audit `detail`) — routes/entitlements.py:184
- §3.4 — insert — a sub-one-day window gives zero window days and `settled_cents` of 0 — calc.py:143-144
- §3.5 — insert — revocation `reason` recorded nowhere; revocation appends no audit row — routes/shops.py:195-203
- §3.5 — insert — seating gates neither the entitlement's `status` nor the technician's `identity_status` — routes/entitlements.py:215-236
- §3.5 — insert — cascaded session/job rows carry `SYSTEM` + null actor in both the explicit and cascaded revoke forms — services.py:225-243
- §3.6 — insert — the (model, area, type) triple is not unique — routes/publications.py:32-52
- §3.7 — insert — the seat's own status is unchecked at session request — routes/sessions.py:57-80
- §3.7 — insert — tool `status` is not a gate; `occupied_by_session_id` names the most recently activated session and is cleared only when it still matches — routes/sessions.py:176-177, services.py:146
- §3.7 — insert — neither close branch stamps `termination_reason` — routes/sessions.py:206-219
- §3.8 — insert — queueing checks nothing beyond the pinned version (not session status, not credential expiry) — routes/sessions.py:261-289

**Orchestrator verification:** `PRD_COMPLETED.md` is 409 lines with 27 headings, ending at the complete `## 5. Error Code Catalogue` table (`ERR_INSUFFICIENT_DATA_CREDIT | 402`) — no truncation. `find implementation -newermt "2026-09-02 23:12" -name '*.py'` returns nothing, confirming Steps 8 and 9 touched no implementation file, so the Step 7 evidence (8/8 rounds at 95/95) remains valid for the delivered code. Pipeline complete.
