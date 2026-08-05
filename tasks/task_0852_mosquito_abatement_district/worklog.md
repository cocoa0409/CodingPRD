# Worklog — task_0852_mosquito_abatement_district

Scenario: 852. Mosquito Abatement District: service area & larval/adult surveillance, trap count & arbovirus (WNV) lab, treatment (larvicide/adulticide/spray) scheduling & route, weather & threshold trigger, complaint & service request, sensitive-site (apiary/organic) registry, aerial-spray notification, reporting

Difficulty: Expert (passed only to Step 2 scaffold-generator).

## Step 1: Task directory — 2026-07-26T00:00:00.000Z

Pre-assigned folder used as-is: `/home/ubuntu/github/CodingPRD/tasks/task_0852_mosquito_abatement_district` (index scan skipped per orchestrator instruction).

## Step 3: Copy shared files — 2026-07-26T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (run early; independent of Step 2).

## Step 2: Generate scaffold (Expert) — 2026-07-26T07:40:00.000Z

All three scaffold artifacts are generated and verified.

## Output files
- `/home/ubuntu/github/CodingPRD/tasks/task_0852_mosquito_abatement_district/SCAFFOLD.yaml` (§1.0–§1.7 + preamble, `global_conventions`, `constants`; neither design key present)
- `/home/ubuntu/github/CodingPRD/tasks/task_0852_mosquito_abatement_district/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_0852_mosquito_abatement_district/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Counts (Expert)
| Dimension | Count |
|---|---|
| Entities | 14 |
| Endpoints | 47 (24 POST / 23 GET, incl. 1 `/_clock` test-driving endpoint) |
| Errors | 53 |
| Roles | 7 (`segregation_of_duties`) |
| State machines | 7 |
| Calculations | 14 (incl. 3 dual-variant, 2 conservation invariants) |
| Validations | 21 priority tiers |
| OCC concurrency rules | 2 |
| §1.8 difficulty instances | 23 (all 9 rules ≥ 2) |
| §1.9 corner instances | 61 (59 with recipes + 2 `excluded_because` stubs) |

## Design shape
- Archetype: compliance/audit × temporal windowing; **flat** topology, **parallel** state-machine shape, segregation of duties.
- Pipelines: `TrapCollection → LabPool → RiskAssessment → ServiceArea.risk_posture` gates `TreatmentPlan → TreatmentRoute`; `ServiceRequest` reacts to posture escalation.
- Non-linear machines: LabPool retest cycle, TreatmentPlan branch + RETURNED→DRAFT + COMPLETED→IN_PROGRESS revert, Notification retry cycle, ServiceRequest parallel axes + reopen cycle.
- Dual variants across different domains: `vector_index` PROVISIONAL 64.31 vs CONFIRMED 78.88 (IN_TESTING pools presumed-negative vs excluded), and `route_pesticide_volume` ESTIMATED 1000.00 vs ACTUAL 1100.00 ml (wind drift).
- Combinatorial modes (a)(b)(c): weighted 4-input index with a `>= 50.00` outbreak branch; degree-days rounded per day then summed (24.2 vs 24.1); admin-fee tier keyed on subtotal 99900 → 0.08/7992/107892 (vs 0.06/5994/105894 if keyed on total).
- Two interval semantics on different resources: applicator occupancy half-open + 45-min trailing buffer (12:45 OK, 12:44 conflict) vs area re-entry closed boundary by active ingredient (exact 12h boundary rejected).
- Two conserved quantities: `on_hand+committed+applied == received_total_ml` (ml) and `open+resolved+closed == total` (case counts).
- Cascades: 5-hop from a POSITIVE lab result down to ServiceRequest `due_at`; 4-hop from route VOID reverting a COMPLETED plan.

## Verification
- All three files `yaml.safe_load` cleanly (`OK`).
- `scaffold_lint.py` → **`VERDICT: clean lint`** over 980 calls, 84 active instances, checks (a)–(f) incl. FK reverse-reachability.
- Extra checks I ran: 86 unique instance names, 0 unbound `${var}` placeholders, 0 dangling `grounds` refs, all 53 error ids exercised in the design files, no forbidden concurrency vocabulary, every named constant (43 + a per-type buffer map) has an explicit numeric value.
- All formula-derived assertions were computed with `Decimal`/ROUND_HALF_UP before being written as literals (64.31, 78.88, 54.20, 68.75, 70.00, 24.2, 12.6/11.6, 1100.00, 28080, 107892, 106000, 12960, 5.00/10.00, 26.25).

One constant I deliberately tuned for testability: `MAX_SEASONAL_APPLICATIONS: 2` (so `ERR_SEASONAL_LIMIT_EXCEEDED` is reachable with two executed routes rather than six), and it stays compatible with the re-entry instance that commits a third route after one execution.

Orchestrator verification: SCAFFOLD.yaml 2710 lines, DIFFICULTY 2109, CORNER 3821; all three `yaml.safe_load` OK.

## Step 4: Generate PRD — 2026-07-26T07:55:00.000Z

PRD generated at `workspace/PRD.md` (493 lines, ~13.9k words). Design files were not opened; no sibling task directory was read.

## Required counts

1. **Endpoints**: 47 documented in §4 = 47 in `SCAFFOLD.yaml` `endpoints` ✅
2. **Error IDs**: all 53 appear verbatim in PRD.md (each in §5 with its HTTP status, and each with its trigger condition in §2/§3 prose) ✅
3. **Constant values**: all 43 scalar declared constants' numeric values appear in prose ✅ (the 44th key, `SENSITIVE_SITE_BUFFER_METERS`, is a map whose four values are the four per-type scalars — 1600/800/1600/400 — all present). **No constant is referenced without a declared value; nothing was invented.**

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 134 required, 134 present, 0 missing
- endpoints[].input (request bodies, query params, path-derived ids): 85 required, 85 present, 0 missing
- endpoints[].output structured keys (surveillance-report, clock): 15 required, 15 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 21 checked, 21 expressed in prose (§2.11 states the full 1→21 short-circuit ordering), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_service_area_version / expected_product_version + ERR_STALE_SERVICE_AREA_VERSION / ERR_STALE_PRODUCT_VERSION + 412), 0 missing
- state_machines[].transitions: 47 checked, 47 fully expressed (from/to, every precondition paired with its error id, every side effect incl. the 5-hop positive cascade and the 3-hop void compensation), 0 missing
- calculations[]: 14 checked, 14 fully expressed as prose (no pseudocode; pinned rounding points, dual variants for MIR/vector_index/route volume, both conservation invariants), 0 missing
- validations[] conditions: 21 checked, 21 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 24 endpoints with side effects checked, 24 expressed, 0 missing
- entities[].fields[] structured content: 134 checked, 134 reconstructible (types, defaults, initial values, common_fields:false → no updated_at/version for LarvalInspection & WeatherObservation), 0 missing
- sibling-branch symmetry: 6 groups checked (MIR PROVISIONAL/CONFIRMED, vector_index variants, route volume ESTIMATED/ACTUAL, plan CANCEL from 6 states, route VOID from EXECUTED/VERIFIED, request CLOSE from RESOLVED/RECEIVED), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 941
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 was verified byte-identical to `section-2.2-response-structure.md`. PRD ends at the §5 table with no audit footer.

## Notes on scaffold inconsistencies resolved (not invented)

- The `TreatmentRoute` COMMIT preconditions and `sensitive_site_encroachment` cite stale priority numbers (14/15/16); I followed the authoritative `validations[]` priorities (13 fitness → 14 referential → 15 posture → 16 clearance → 17 re-entry → 18 occupancy → 20 counting → 21 inventory), which matches the COMMIT precondition ordering itself.
- Plan SCHEDULE's encroachment clause is unrestricted by site type in `state_machines`, but both `ERR_NOTIFICATION_INCOMPLETE` and priority-16 clearance restrict it to `APIARY`/`ORGANIC_FARM`; the PRD uses the restricted (two-of-three-sources) reading.
- Priority 17's `product.reentry_interval_hours` is unqualified; the PRD pins it to the product of the route being committed (matching the explicit "this route's product" qualifier in the same clause).
- Plan SUBMIT's "at least one PLANNED route" precondition has no nominated error id in the scaffold; the PRD assigns it `ERR_INVALID_TRANSITION` (the priority-10 generic).
- `IN_TESTING → INVALID` omits the staleness side effect in `state_machines` but the lab-pool endpoint's `side_effects` includes INVALID; the PRD states that all recorded outcomes and DISCARD mark OPEN assessments stale with `LAB_RESULT`.
- The scaffold says "the five /transitions endpoints" in several `applies_to` fields; there are in fact six. The PRD phrases these as "any transition-driving endpoint" to avoid propagating the miscount.

---

## Step 5: Generate unit tests — 2026-07-26T14:35:00.000Z

Test infrastructure and suite are complete and verified.

### Files written

**`test_helpers/`** (Stage 1, 9 files, ~2,300 lines)
- `types.py` — 7-role enum, 19 status/enum types, 15 entity TypedDicts (`LarvalInspection`/`WeatherObservation` correctly carry only `id` + `created_at` — no `updated_at`, no `version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (47 endpoints incl. `/_clock/set_current_utc` and the surveillance report)
- `api_errors.py` — 53 error ids + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions plus the two conservation checkers (`assert_inventory_partition`, `assert_request_count_partition`), three-fractional-digit timestamp checker, `assert_index`
- `constants.py`, `factories.py`, `test_users.py` (per-instance builders `make_field_tech_headers` / `make_site_operator_headers` for the two entity-backed roles), `fixtures.py` (909 lines: primitives + posture/plan/route/notice/complaint tiers + 9 named scenario builders such as `setup_surveillance_dual_variant`, `setup_reentry_boundary_scenario`, `setup_area_at_seasonal_cap`, `setup_aerial_plan_awaiting_schedule`), `__init__.py` barrel

**`test_suite/`** (Stage 2, conftest + 11 domain-named files, ~3,750 lines) — **107 tests**, all collected by pytest.

### Coverage audit

| Queue | Instances | Translated | Skipped |
|---|---|---|---|
| A — `SCAFFOLD_DIFFICULTY_DESIGN` (9 rules) | 23 | **23 × 2 tests = 46** | 0 |
| B — `SCAFFOLD_CORNER_DESIGN` (8 sections) | 61 non-stub | **61 × 1 test = 61** | 0 |
| B — `excluded_because:` stubs | 2 | not translated (by contract) | — |

Both stub cross-references resolve to real difficulty instances (`lab_positive_cascades_five_hops_to_service_request_priority`, `service_request_case_count_partition_unchanged_by_resolve_then_reopen`), so no placeholders were emitted. **No instance was dropped for PRD-coverage or unique-derivability reasons** — every claim in both indices is named verbatim in PRD prose with a single derivable outcome (the §2.11 21-step precedence list and the §3.9 nine-condition commit order made the four priority-pair instances derivable rather than error-precedence gaps).

### Self-verification (all green)
- `py_compile` on every file; `pyflakes` clean (no undefined/unused names outside the barrel)
- Machine audit against both YAMLs: 107 tests → 107 `Design:` tags, **exactly one per docstring**, every tag resolves to a real instance with the correct `rule_id`/`section`; no difficulty instance below 2 tests, no corner instance below 1
- Every quoted PRD citation (whitespace-normalized) survives a literal match against `workspace/PRD.md`
- `grep -rn "skip\|xfail"` → none; no `examples/` directory created

Notable pinned values asserted verbatim from the design indices: provisional 6.67/64.31 vs confirmed 10.00/78.88, degree-days 24.2 (round-per-day), vector index 54.20 (no amplification at component 48.00) and 68.75 (amplification at exactly 50.00), posture EMERGENCY at exactly 70.00, admin fee 0.08/7992/107892 (tier from subtotal) vs 0.06/6000/106000 at subtotal 100000, drift 1000.00→1100.00 ml at exactly 8.0 mph, occupancy strict 12:44 vs 12:45 boundary, re-entry closed boundary 00:00 vs 00:01, and both conservation partitions before/after their compensating operations.

*Orchestrator verification: 107 `def test_` / 107 `Design:` tags, 0 skip/xfail markers, all files compile.*

---

## Step 6: Generate implementation — 2026-07-26T14:35:00.000Z

All checks pass. Final verification summary:

**Files written** (`workspace/implementation/`)

| File | Role |
|---|---|
| `start.sh` | Guarded `pip install`, `exec python3 app.py`, reads `$PORT` |
| `requirements.txt` | `Flask>=2.0` |
| `app.py` | Blueprint registration, error handlers, `Connection: close` `after_request`, `0.0.0.0:$PORT` foreground |
| `common.py` | Errors, envelope (`meta`/`response_type`/`data`), **single** 3-digit datetime renderer, logical clock, Decimal helpers, auth, validators, pagination |
| `store.py` | In-memory dicts (empty at boot, nothing seeded), `fetch`/`not_found` per-entity 404 map, `new_record`/`touch`, `ordered` |
| `calc.py` | All constants + pinned arithmetic (indices, MIR variants, vector index, posture, volumes, cost waterfall, encroachment) |
| `views.py` | Per-entity field projections (larval inspections/weather observations omit `updated_at`/`version`) |
| `domain.py` | Cross-aggregate ops: staleness, posture recompute + complaint fan-out, ledger movements, transition scaffolding |
| `api_area.py`, `api_lab.py`, `api_product.py`, `api_plan.py`, `api_route.py`, `api_notification.py`, `api_request.py` | 47 endpoints |

**Route count: 47 / 47** (exact match with the scaffold endpoint table).

**Verification**: `py_compile` + `ast.parse` clean on all 13 modules; server boots from a fresh process via `bash start.sh` and serves requests; 4 smoke suites (~130 assertions) all green — covering the positive-detection 5-hop cascade, both MIR/vector-index variants, outbreak amplification + cap, round-then-sum degree days (24.2 not 24.1), the conserved pesticide partition across COMMIT/EXECUTE/VOID/RELEASE, cost waterfall (550/14400/14950/1196/16146), AERIAL 2-approver quorum + SoD, encroachment clearance, ack-window boundary (24h belongs to the operator), occupancy 45-min buffer strictness, seasonal cap, reopen 30-day boundary, OCC 412s, and validation-precedence ordering.

**Traps pre-avoided**: all datetimes stored as `datetime` and rendered by one `render_dt` at the envelope boundary (clock setter included — `/_clock/set_current_utc` echoes through the same renderer); `str(uuid.uuid4())` dashed IDs; `Connection: close` after_request; foreground `exec` launcher.

**PRD ambiguities resolved**

1. **`ERR_COLLECTION_HAS_POOLS` reachability** — creating the first pool auto-advances `SUBMITTED → POOLED`, so a literal "VOID from SUBMITTED needs zero pools" makes the catalogued error dead. Chose: VOID from `LOGGED` unconditional; from `SUBMITTED`/`POOLED` gated on "no pool ever existed" → `ERR_COLLECTION_HAS_POOLS` (so VOID on a pooled collection returns the declared error, not `ERR_INVALID_TRANSITION`).
2. **Escalation gating** — complaint priority fan-out fires only when the recomputed posture is *strictly higher* rank (PRD §3.6), at both recomputation sites including LabPool positive cascade hop 5.
3. **Missing vs unknown `action`** — absent/non-string `action` → `ERR_VALIDATION` (step 6 "required fields present"); an unrecognised action string → `ERR_INVALID_ACTION` (step 7).
4. **Re-inspection self-loop** — omitted `verification_status` on `INSPECTED → INSPECTED` → `ERR_VALIDATION` (PRD calls it "mandatory").
5. **SCHEDULE encroachment clearance** — restricted to `APIARY`/`ORGANIC_FARM` per PRD §3.8 (scaffold's precondition said "every SensitiveSite").
6. **Re-entry interval source** — uses the *committing* route's product's `reentry_interval_hours` (PRD §3.9 "declared on the product this route will apply").
7. **Notification SEND with a non-`APPROVED`/`SCHEDULED` plan** — no dedicated error declared; returns `ERR_INVALID_TRANSITION` (409), consistent with notice issuance.
8. **Body FK typing** — a supplied-but-unresolvable FK (any type) yields the entity 404 at step 4; an absent FK falls through to `ERR_VALIDATION` at step 6.
9. **Decimal-place constraints** (e.g. `tmax_c` "at most 1 decimal place") are *not* enforced as `ERR_VALIDATION` — the scaffold's `ERR_VALIDATION` trigger list omits them; ranges and `tmin_c <= tmax_c` are enforced.
10. **`meta.api_request_timestamp`** uses wall clock (rendered by the same 3-digit renderer); every domain/stamped datetime uses the logical clock.

*Orchestrator verification: independent `url_map` walk confirms 47 registered routes (excluding `static`) == 47 scaffold endpoints; all modules compile.*

---

## Step 7: Run tests and iterate — 2026-07-26T14:45:00.000Z

Clean 8-round sweep. Exiting.

**Iterations run:** 2

**Final per-round tallies** (`workspace/implementation/results.1..8.json`):

| round | total | passed | failed | errors |
|---|---|---|---|---|
| 1–8 (all) | 107 | 107 | 0 | 0 |

**Tests deleted:** none. The single failure passed both STEP 1a (PRD verbatim-covers) and STEP 1b (unique derivability), so it was resolved as a test bug at STEP 2.

**Fixes applied to `test_suite/`:**
- `test_suite/test_10_inventory_and_concurrency.py`, `test_every_uniqueness_scope_reports_duplicate_resource` — the duplicate-trap-site probe sent `"habitat": "MARSH"`, which is the **larval-inspection** habitat enum (PRD §, `CATCH_BASIN`/`DITCH`/`MARSH`/`CONTAINER`), not the **trap-site** habitat enum (PRD line 205: "the dominant `habitat` at the location — `URBAN`, `WETLAND`, `AGRICULTURAL`, or `STORMWATER`"). Changed to `"WETLAND"`.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none. Route count unchanged at 47/47.

**Diagnosis detail (why this was a test bug, not an impl bug):** PRD §2.11 fixes validation precedence — step 6 *Request shape* ("enum values inside their declared sets" → `ERR_VALIDATION`) is evaluated **before** step 9 *Uniqueness* (`ERR_DUPLICATE_RESOURCE`, HTTP 409). A PRD-faithful implementation must therefore reject the out-of-set `MARSH` habitat with `ERR_VALIDATION` before ever reaching the `site_code` uniqueness check, which is exactly what the server did. Weakening or reordering the enum check would have violated the cardinal rule against removing a PRD-required check. Verified against a scratch server that all four uniqueness scopes in that test (`ServiceArea.code`, `TrapSite.site_code` per-area, `PesticideProduct.epa_reg_no`, `WeatherObservation` per area+`obs_date`) return `ERR_DUPLICATE_RESOURCE` / 409 once the payload is PRD-valid.

**Flakiness:** none observed — the failure was deterministic across all 8 rounds pre-fix, and all 8 rounds are green post-fix. No boot-timeout or saturation artifacts appeared in either sweep.

*Orchestrator verification (independent of the subagent's claim): all 8 `results.N.json` re-read — each `total=107 passed=107 failed=0 errors=0`, zero non-passed entries in the per-test arrays; `grep` for `pytest.mark.skip`/`xfail` across `test_suite/` and `test_helpers/` → none; 107 `def test_` / 107 `Design:` tags (no test lost to the fix); `url_map` walk → 47 routes. Sweep executed via `sweep.sh` as 2 waves of 4 concurrent rounds.*

---

## Step 8: Finalize PRD — 2026-07-26T14:50:00.000Z

`workspace/PRD_FINALIZED.md` created. **Byte-identical to PRD.md** (same md5 `2d0c4909d668ceee6e557b5eba2c0f74`).

- PRD.md: 493 lines — PRD_FINALIZED.md: 493 lines — **delta 0 lines (0.00%)**
- Changes: **none**. Zero inserts, zero revisions.

### Why no patch was warranted

The sole `<step_7_diff>` item was a test-side payload bug (`"habitat": "MARSH"` sent to the trap-site create endpoint) with zero impl fixes and zero deletions. The mandated verification was performed rather than assumed.

**Check 1 — are the two `habitat` enums distinct enough for a PRD-only reader?** Yes. `grep -n "habitat\|URBAN\|STORMWATER\|AGRICULTURAL\|CATCH_BASIN\|DITCH\|CONTAINER\|MARSH"` over PRD.md returns exactly two lines, each binding its enum to one entity in prose, with no shared/global "habitat enum" definition and no field-table appendix that could imply one:
- PRD.md:205 (§3.1, TrapSite) — "the dominant `habitat` at the location — `URBAN`, `WETLAND`, `AGRICULTURAL`, or `STORMWATER`"
- PRD.md:247 (§3.5, LarvalInspection) — "the `habitat` inspected, which is one of `CATCH_BASIN`, `DITCH`, `MARSH`, or `CONTAINER`"

These match the impl's two disjoint tuples verbatim (`implementation/api_area.py:23-24`: `TRAP_HABITATS`, `LARVAL_HABITATS`) and their three consumption sites: create trap site (`api_area.py:139`, TRAP), create larval inspection (`api_area.py:197`, LARVAL), list larval inspections `?habitat=` filter (`api_area.py:218`, LARVAL). The trap-site listing (`api_area.py:164-174`) filters only on `is_active`, exactly as PRD:205 says — no habitat query filter exists to be under-specified.

**Check 2 — is §2.11's shape-before-uniqueness precedence unambiguous?** Yes. §2.11 states "Checks are evaluated in the following order, and the first failure short-circuits the request," with step 6 *Request shape* ("enum values inside their declared sets … `ERR_VALIDATION`") strictly preceding step 9 *Uniqueness* (`ERR_DUPLICATE_RESOURCE`, 409). `implementation/api_area.py:132-146` validates `site_code`/`trap_type`/`habitat`/`x_m`/`y_m`/`is_active` before the `site_code` duplicate scan — the exact behavior the test hit.

### Pre-edit search log (run despite the null outcome)

Zero edits committed, but the NO-NEW-MISMATCH search was run for the one candidate subject in case a patch was needed:

- **(a) Subject:** the `habitat` enum sets and the §2.11 request-shape-vs-uniqueness ordering.
- **(b) Impl paths enumerated and read/grepped:** `grep -rn "habitat|WETLAND|MARSH"` across all impl `.py` → `api_area.py:23,24,139,153,197,206,218,221`, `views.py:26,43`; read `api_area.py:110-240` in full. Separately enumerated **every** uniqueness site via `grep -rn "duplicate(|ERR_DUPLICATE_RESOURCE"` and read each in context to confirm the §2.11 ordering claim holds globally, not just at the Step 7 site: `api_area.py:49` (area `code`), `api_area.py:146` (trap-site `site_code`), `api_area.py:245` (weather `obs_date`), `api_lab.py:51` (live collection per trap-site-day), `api_plan.py:143` (`route_code` per plan), `api_notification.py:52` (live notice per plan+site), `api_product.py:37` (`epa_reg_no`), `api_product.py:105` (`license_no`). All eight run full body validation before the duplicate scan, and the two that also have state gates (`api_plan.py:145-147`, `api_notification.py:56-58`) place those gates *after* the duplicate check — consistent with §2.11 steps 9 → 10/11. No wording in §2.11 or §3.1/§3.5 mis-describes any of them.
- **(c) Wording adjustment:** none required — every enumerated path is already correctly described by the existing prose.

Step 7's adjudication holds: PRD.md already uniquely determines the behavior at that site, so a fresh implementer reading PRD_FINALIZED.md alone would reject the out-of-set `MARSH` trap-site habitat with `ERR_VALIDATION` before reaching the uniqueness check, exactly as `implementation/` does.

*Orchestrator verification: `diff -q PRD.md PRD_FINALIZED.md` → identical; both 493 lines, md5 `2d0c4909d668ceee6e557b5eba2c0f74`. Step 8 was NOT skipped (Step 7 ran 2 iterations with 1 `test_suite/` fix), and it correctly concluded with a null patch.*

---

## Step 9: Complete PRD — 2026-07-26T15:05:00.000Z

`workspace/PRD_COMPLETED.md` is written.

### Size
- `PRD_FINALIZED.md`: 493 lines / 98,029 chars → `PRD_COMPLETED.md`: 495 lines / 105,845 chars (**+2 lines, +7,816 chars**)
- 24 changed lines across 25 in-place edits; no new sections, no new headings (29 headings before and after). Only one insert added lines (the §2.4 version paragraph).

### Counts
- **6 mismatch-revisions**, **19 ambiguity-pins**

### Changes
- §2.2 — revise — mismatch — `meta.api_request_timestamp` is envelope metadata on the host **wall clock**, the sole exception to §2.4's logical-clock rule — `common.py:334`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` → `ERR_VALIDATION`; empty-string pagination params and empty-string filters treated as omitted — `common.py:399-412`
- §2.3 — revise — ambiguity — `created_at` ties (routine under a frozen logical clock) break by persistence order — `store.py:96-98`
- §2.3 — revise — ambiguity — out-of-set enum filters → `ERR_VALIDATION`; identifier filters are never resolved (unknown id → empty page, not 404) — `common.py:421-446`
- §2.4 — insert — ambiguity — `version` counts writes not requests: confirm writes the area twice (+2 only when posture/source actually changed), cancel writes the plan twice; a no-op posture recompute writes nothing; a re-asserted duty status still writes — `api_area.py:373-377`, `api_plan.py:345,367`, `domain.py:66-72`
- §2.5 — revise — ambiguity — a present-but-non-string body FK is unresolvable → that entity's 404 (not `ERR_VALIDATION`); absent/null FK falls to step 6 — `store.py:62`, `api_plan.py:39-44`
- §2.6 — revise — mismatch — decimal-place counts are output precision, never input constraints; pinned which fields are quantised half-up to 2dp (`received_total_ml`, `delta_ml`, `planned_acres`, `actual_acres`) vs stored verbatim (`label_rate_ml_per_acre`, `wind_speed_mph`, `ct_value`, `rainfall_mm`, `tmax_c`, `tmin_c`) — `api_product.py:40,80`, `api_plan.py:159`, `api_route.py:223`
- §2.11 step 7 — revise — ambiguity — absent/null/non-string `action` → `ERR_VALIDATION` at step 6; unrecognised *string* → `ERR_INVALID_ACTION`, never `ERR_UNAUTHORIZED`; action-specific body fields validated only for declared actions — `domain.py:136-162`
- §3.2 — revise — ambiguity — `restricted_use` optional, defaults false — `api_product.py:33`
- §3.2 — revise — ambiguity — adjustment `reason` required (1–500 chars); `delta_ml` quantised to 2dp before application — `api_product.py:72-80`
- §3.3 — revise — ambiguity — submission window has no lower edge: a future `collection_date` never trips `ERR_COLLECTION_WINDOW_EXPIRED` — `api_lab.py:117-120`
- §3.3 — revise — **mismatch** — VOID is available from `SUBMITTED` *or* `POOLED`; since the first pool advances the collection to `POOLED`, `ERR_COLLECTION_HAS_POOLS` is reachable only from `POOLED`, `SUBMITTED` always voids, `VOIDED` → `ERR_INVALID_TRANSITION`; `void_reason` optional (1–1000) — `api_lab.py:125-143`
- §3.4 — revise — ambiguity — the collection gate is re-applied on the `INVALID → IN_TESTING` retest edge and precedes the retest limit — `api_lab.py:228-234`
- §3.4 — revise — **mismatch** — positive-cascade hop 5 fires *only* on a strictly higher posture rank, and `due_at` is recomputed only where the priority actually rose; a positive into an already-`ELEVATED`/`EMERGENCY` area fans out to nothing — `domain.py:46-73`, `api_lab.py:293`
- §3.5 — revise — **mismatch** — `tmax_c`/`tmin_c` range and ordering are enforced; the "at most one decimal place" convention is not — `api_area.py:237-240`
- §3.7 — revise — **mismatch** — `duration_minutes` is whole minutes **truncated downward**, so a sub-minute window yields 0 (not "always at least 1") — `api_plan.py:149`
- §3.7 — revise — ambiguity — `return_reason` optional (1–1000), null when omitted — `api_plan.py:198`
- §3.7 — revise — ambiguity — `cancel_reason` optional (1–1000), null when omitted — `api_plan.py:200`
- §3.7 — revise — ambiguity — cancellation leaves `ACKNOWLEDGED`/`FAILED`/`UNDELIVERABLE` notices alone, then recomputes `estimated_total_ml`, and touches neither the cost record, `completed_at`, nor `seasonal_application_count` — `api_plan.py:340-367`
- §3.8 — revise — ambiguity — notification SEND against a plan outside `APPROVED`/`SCHEDULED` → `ERR_INVALID_TRANSITION` (409), checked before the attempt cap; `failure_reason` optional (1–1000) — `api_notification.py:126-131,117`
- §3.9 — revise — ambiguity — the re-entry scan covers every `EXECUTED`/`VERIFIED` same-ingredient route in the area regardless of plan and regardless of whether its window is chronologically earlier — `api_route.py:151-164`
- §3.9 — revise — ambiguity — route `void_reason` optional (1–1000) — `api_route.py:74`
- §3.10 — revise — ambiguity — omitted `verification_status` on the `INSPECTED → INSPECTED` self-loop → `ERR_VALIDATION` at step 6 (before transition existence); optional in every other state — `api_request.py:147-151`
- §3.10 — revise — ambiguity — `resolution_note` bounded 1–1000 characters — `api_request.py:153`
- §3.10 — revise — ambiguity — reopen leaves `resolved_at` and `resolution_note` standing rather than clearing them — `api_request.py:221-234`

Deliberately **not** documented: the `Connection: close` `after_request` header (`app.py:54-59`) — transport workaround, not domain behavior.

*Orchestrator verification: PRD_COMPLETED.md is 495 lines (+2 over PRD_FINALIZED.md), 48 diff lines, heading count unchanged at 29 (no new sections). `find` confirms no `.py` under `implementation/`, `test_suite/`, or `test_helpers/` was modified after the final green sweep, so `results.1..8.json` (8×107/107) remain valid for the shipped artifacts.*

---

## Pipeline complete — 2026-07-26T15:05:00.000Z

All 9 steps done. Final state: 107 tests, 8/8 sweep rounds at 107 passed / 0 failed / 0 errors; 47 endpoints implemented (== 47 scaffold endpoints); 0 tests deleted; 0 implementation fixes; 1 `test_suite/` fix. Artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/`, `test_suite/`, `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}`.

## Post-pipeline verification — 2026-07-26T14:20:00.000Z

The sibling task `task_0854_body_art_tattoo_permit` reported in its own Step-7 log that it had mistakenly killed several of this task's `app.py` server processes while reaping what it believed were its own orphans, during one of this task's sweeps. To rule out contaminated evidence, an independent 8-round sweep (2 waves of 4, same `--isolation per-test-server` invocation) was re-run on a fully idle host after every orchestrator had exited.

Result: **8/8 rounds, 107/107 passed, 0 failed, 0 errors** — identical to the durable `results.{1..8}.json` already on disk. No contamination; the on-disk results stand. The temporary verification files were removed and no task artifact was modified.
