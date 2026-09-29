# Worklog — task_2590_commercial_laundry_equipment_manufacturing

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2590_commercial_laundry_equipment_manufacturing/` and `workspace/` (pre-assigned path; no index scan performed per orchestration instructions).

## Step 2: Generate Scaffold — 2026-09-03T01:30:00.000Z

All three scaffold artifacts for task 2590 are complete and lint-clean.

## Files

| Path | Lines | Top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | 2954 | `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (contains neither design key) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1727 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3470 | `scaffold_corner_design` only |

## Counts

- 12 entities (MachineModel, RebateProgram, CertificationDossier, ServicePart, AssemblyStation, Technician, BuildOrder, StationLog, Distributor, PackageQuote, QuoteLine, WarrantyClaim; StationLog and QuoteLine are `common_fields: false`), graph topology with a self-referential `supersedes_part_id`.
- 52 endpoints under prefix `/clm`, 9 state machines / 45 transitions, 8 calculations, 2 §1.2.1 concurrency rules, 57 validations, 49 error codes, 9 roles.
- §1.8: 18 difficulty instances. §1.9: 78 corner instances across all nine claim-guide sections — entities 13, state_machines 13, calculations 10, validations 20, endpoints 4, errors 5, rbac 5, cross_cutting_complexity_layers 6, consistency_model 2 — of which 14 are `excluded_because` stubs citing a §1.8 instance by name, leaving 64 full test recipes (741 structured calls total across both design files).

## Verdict block (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     64
  Calls scanned (§1.8+§1.9):  741

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design adjudications made while writing §1.9

- **Validation-priority pre-emption** drove several restructurings: a station_type-mismatch test had to keep the body's `station_type` consistent with the build state (else priority 26 `ERR_BUILD_STATE_INVALID` fires before 39) and grant the technician both scopes (else 36 pre-empts 39); the double-booking test uses two distinct stations so 45 cannot mask 46; the unknown-FK claim test asserts `ERR_PART_NOT_FOUND` because body FK checks are ordered 17 (part) before 18 (build).
- **RBAC-before-existence** was used deliberately: peer-role and undeclared-role denials fire at priority 2 against random UUIDs, so those recipes need almost no fixtures.
- **Error triggerability** was closed by consolidating eleven path-id 404s into one instance asserting eleven distinct error codes, plus dedicated instances for the otherwise-unreached `ERR_TECHNICIAN_STATE_INVALID` (RENEW before any GRANT) and `ERR_QUOTE_STATE_INVALID` (decision on DRAFT); `ERR_CLAIM_STATE_INVALID` is asserted as a re-adjudication tail on the OCC instance.
- **OCC framing**: the part-version rule is written to show the token guards a *sibling* aggregate (a stock receipt invalidates the analyst's token while the claim row is untouched), which rules out implementing it against the claim's own version.
- **Threshold conjunction**: the distributor authorization instance satisfies module coverage first (one technician holding both modules stays PENDING_TRAINING) so a row count cannot substitute for a distinct-technician count.
- **Cross-cutting scope** was limited to the four layers actually declared in `complexity_profile` (optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers); pagination/filtering claims live in the entities `listing` instance instead.
- Enum/format errors caught and fixed against SCAFFOLD.yaml during authoring: `ERR_INVALID_REQUEST` is 400 (not 422), `probation_reason` WARRANTY_ABUSE, `suspended_reason` MANUAL, defect_code CONTROL_FIRMWARE, `completed_on` as a plain date, and there is no `CONTROL_DONE` build state (post-control state is QA_HOLD).

## Step 3: Copy shared files — 2026-09-03T01:35:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2590_commercial_laundry_equipment_manufacturing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T01:55:00.000Z

PRD generation for task 2590 is complete.

**Output:** `workspace/PRD.md` — **531 lines**

**Sections written**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications, 12 domain-derived subsections: 2.1 RBAC · 2.2 API Response Structure (byte-identical verbatim block) · 2.3 Pagination · 2.4 Resource Identity/Timestamps/Versioning · 2.5 The Logical Clock and Its Two Sweeps · 2.6 Money, Percentages and Rounding Discipline · 2.7 Optimistic Concurrency Control · 2.8 Validation Precedence (all 57 rules enumerated in global order) · 2.9 Nested Path Resolution · 2.10 Segregation of Duties · 2.11 Cascade Discipline · 2.12 Natural Keys and Code Formats
- §3 Business Logic, 9 subsections: catalogue · rebate programs · certification/release/recertification · technician certification + revocation cascade · assembly floor + occupation windows · final inspection + yield-breach cascade · distributor channel · package quoting + financing · warranty claims + stock movement
- §4 Endpoint Definitions — 4-column table, 52 rows (generated from the scaffold, so method/path/description/roles are exact)
- §5 Error Code Catalogue — 49 rows

**Coverage counts (scaffold → PRD, all 100%)**
12 entities / 147 entity field names · 52 endpoints · 105 request-body identifiers · 30 query params · 49 errors · 9 roles · 9 state machines / 45 transitions · 8 calculations · 57 validations · 2 concurrency rules.

**Hard Contract results**
- **Contract 1 (Field-Name Coverage) — PASS.** MISSING fields [], body [], query [], errors [], roles [], states [], enums [].
- **Contract 2 (Rule Coverage) — PASS.** All 57 validations appear with their `error_id`, HTTP status and `applies_to` scope in the §2.8 precedence chain; both OCC rules (`expected_quote_version`→`ERR_STALE_QUOTE_VERSION` 412, `expected_part_version`→`ERR_STALE_PART_VERSION` 412) in §2.7; all 45 transitions with preconditions and side effects; all cross-entity cascades hop-by-hop (certification cascade, 4-hop revocation cascade + 3-hop re-grant unwind, 6-hop yield-breach cascade, stock enter/leave-`BACKORDERED` cascades, conjunctive unblock rule); all 8 calculations including both dual-variant pairs, the rounding-order trap, the pre-fee tier trap, the uncapped-vs-capped ranking trap, the floor-once rule on `effective_rated_cycles`, and the closed-vs-half-open interval asymmetry; sibling-branch symmetry covered for ENERGY/WATER, both →`SUSPENDED` paths, DRAFT/REVISION_REQUESTED→SUBMITTED, the three quote decisions, and APPROVE/DENY adjudication.
- **Contract 3 (§3 Path Purity) — PASS.** 1152 backtick tokens scanned in §3: 0 begin with `/`, 0 bare HTTP methods, 0 method+path tokens, `/clm` absent from §3 entirely.

**Tail confirmation:** the file ends on the last row of the §5 table, `| \`ERR_STOCK_ADJUSTMENT_NEGATIVE\` | 422 |` — a complete section boundary, no mid-sentence truncation. Written in 12 chunked `cat >>` appends; line count grew monotonically 78→531 with no failed write.

**One scaffold inconsistency resolved by judgement:** `QuoteLine.line_discount_pct` is constrained `0.00..20.00` in the entity table but described as `0.00..40.00` in `calculations.quote_line_total.inputs`. The PRD states `0.00` through `20.00`, since validation priority 3 checks each field's declared entity range.

### Orchestrator notes on Step 4

- Verified the PRD tail independently: 531 lines, final line is the last `ERR_STOCK_ADJUSTMENT_NEGATIVE` row of the §5 error table — a real section boundary, not a mid-sentence truncation. No regeneration needed.
- Adjudicated the `line_discount_pct` 20-vs-40 discrepancy myself: grepped both design indices; every `line_discount_pct` literal used in any test recipe is 0.00 or 2.50, and no instance targets the upper boundary or an out-of-range discount error. The discrepancy is therefore untested and cannot produce a Step 7 failure. Left the PRD's 20.00 wording as-is.

## Step 6: Generate Implementation — 2026-09-03T02:50:00.000Z

Implementation complete. All source lives in `workspace/implementation/`.

## Files written (line counts)

| File | Lines | Role |
|---|---|---|
| `app.py` | 64 | Flask factory, `ApiError`/`HTTPException` handlers, `PORT` env boot |
| `start.sh` | 10 | launcher (installs flask only when missing, then `exec python3 app.py`) |
| `requirements.txt` | 1 | `flask>=3.0` |
| `db.py` | 71 | in-memory `Store` (12 dicts), logical clock `2026-08-01T00:00:00Z`, `base_row/bump/order_*/by_key` |
| `errors.py` | 132 | 47 error ids + HTTP status map + `fail()` |
| `response.py` | 100 | envelope, `req_` ids, 3-digit ISO timestamps, Decimals as raw JSON numbers |
| `validate.py` | 252 | rule-3 schema validation, pagination |
| `middleware.py` | 90 | rules 1/2, acting technician/distributor, `require_certified` |
| `lookup.py` | 74 | path/body resolution with per-entity 404 ids |
| `services/calc.py` | 227 | every §3 formula at prec 50, one round-half-up each |
| `services/cascades.py` | 256 | derived refreshes + revocation / regrant / yield-breach / stock cascades |
| `routes/machine_models.py` | 185 | 5 endpoints |
| `routes/rebate_programs.py` | 106 | 3 |
| `routes/dossiers.py` | 163 | 5 |
| `routes/service_parts.py` | 109 | 4 |
| `routes/assembly_stations.py` | 64 | 3 |
| `routes/technicians.py` | 138 | 4 |
| `routes/build_orders.py` | 284 | 8 |
| `routes/distributors.py` | 163 | 5 |
| `routes/quotes.py` | 289 | 9 |
| `routes/warranty_claims.py` | 220 | 5 |
| `routes/clock.py` | 45 | 1 |

Total 3,043 lines. **52 registered routes, exactly matching the 52 rows of the PRD §4 endpoint table.** Storage is dicts only; the store is empty and the clock is exactly `2026-08-01T00:00:00Z` on every boot (verified by relaunching through `start.sh`).

## Smoke verification (port 39590, killed by pid afterwards; port confirmed free)
92 assertions across three scripts, all green: full happy path (model → dossier double review → release → 3 station logs → QA sign-off → ACCEPTED, yield 100.00), distributor training to AUTHORIZED, quote/line/OCC/submit/revision/delete, part stock, claim FULL_REPLACEMENT + void reversal, warranty-analysis, clock sweeps; revocation → integrity hold → claim block → regrant → unblock → PRO_RATA 13333; rebate qualification 120000 + non-retroactive retirement; yield breach → dossier RESURVEY_REQUIRED + model SUSPENDED/YIELD_RESURVEY + rebates cleared; SoD, territory exclusivity, duplicate training key, stale versions, 401/403/400/404 guards. The §3.8 financing worked example reproduces exactly: fee 123750, principal 5073750, stated 715 → apr 1590 / payment 123114, verified 668 → apr 1690 / payment 125823.

## Judgement calls (PRD ambiguities resolved)
- **§2.8 numbering beats §3 prose ordering** wherever they disagree: qa-signoff checks SoD (35) before certification (36); quote submit gates state (30) → no-lines (53) → not-authorized (54) → `down_payment_cents` (ERR_INVALID_REQUEST, last); claim filing checks cert (36) before technician/distributor mismatch (41).
- **Rule 22 before 23 for Distributors**: a `Distributor` whose `X-User-ID` is not a stored distributor gets `ERR_DISTRIBUTOR_NOT_FOUND` 404, not `ERR_OWNERSHIP_VIOLATION`.
- **Distributor list scoping**: only `GET /clm/quotes` self-filters (the one explicit PRD sentence); `/clm/quote-lines`, `/clm/warranty-claims` lists and `GET /clm/quote-lines/{id}` are unscoped, since rule 23's list of guarded operations is exhaustive.
- **Decimals**: bodies parsed with `parse_float=Decimal`, stored quantized to declared scale, emitted as raw JSON numbers preserving scale (`2.50`); more decimals than declared → `ERR_INVALID_REQUEST`.
- **Optional inputs**: any scaffold field declaring a default is optional, and an explicit JSON `null` is treated as absent.
- **`bearing_preload_micron`** presence/absence violations report `ERR_PRELOAD_OUT_OF_SPEC` (PRD rule 37) rather than `ERR_INVALID_REQUEST`, keyed on the body `station_type`; rule 36's demanded scope comes from the referenced station's `station_type`.
- **Version bumps**: a parent bumps only when a derived value actually changed; a failing station log that also crosses the rework ceiling bumps the build twice (two declared transitions); an adjudication bumps the part exactly once on both APPROVE and DENY.
- **Revocation hop 2** sets `integrity_hold` on every implicated non-SCRAPPED unit and additionally moves the four in-production states to QUALITY_HOLD, leaving ACCEPTED terminal; the yield-breach cascade never sets `integrity_hold` and fires only when a CERTIFIED dossier exists.
- **PROBATION** `reason` is validated as the enum `WARRANTY_ABUSE|MANUAL` (stored in `probation_reason`); TERMINATE takes free text.
- **`warranty-analysis` breakdowns** are objects keyed by class/duty with `{claim_count, covered_amount_total_cents}`; VOIDED money excluded, counts retained.
- **Ordering tie-break**: an internal `_seq` insertion counter (never serialized, like all `_`-prefixed keys) is the final tie-break for every collection so same-instant rows have a stable order.

### Orchestrator note on Steps 5/6 launch
Step 5 and Step 6 were launched as two separate background Agent calls rather than a single message with two tool uses. To preserve the impl generator's isolation despite the ~90s gap, Step 6's prompt carried an absolute prohibition on reading `test_suite/`, `test_helpers/`, and both design YAMLs; its summary shows it worked from PRD.md + SCAFFOLD.yaml + INSTRUCTION.md only.

## Step 5: Generate Unit Tests — 2026-09-03T03:05:00.000Z

Stage 1 and Stage 2 are both complete and audited.

## Files written (all at the task root, nothing under `workspace/`)

**`test_helpers/`** — 2283 lines
`__init__.py` 11, `api_client.py` 530 (52 methods = 51 `/clm` endpoints + the logical clock), `api_errors.py` 130 (49 error ids + `ERROR_HTTP_STATUS` registered via `set_error_http_status_map`), `assertions.py` 121, `constants.py` 169, `factories.py` 421, `fixtures.py` 567 (34 builders + 11 function-scoped fixtures), `test_users.py` 90, `types.py` 244.

**`test_suite/`** — `conftest.py` 37 plus 24 test modules, 5978 lines, **169 tests**:
`test_01_warranty_settlement_variants.py` 141, `test_02_financing_offer_variants.py` 178, `test_03_quote_line_rounding_order.py` 161, `test_04_build_rework_cycle.py` 281, `test_05_dossier_parallel_reviews.py` 129, `test_06_yield_breach_cascade.py` 287, `test_07_certification_revocation_cascade.py` 265, `test_08_validation_precedence.py` 173, `test_09_boundary_precision.py` 172, `test_10_cross_entity_state_gates.py` 165, `test_11_resource_temporal_overlap.py` 229, `test_12_compensating_invariants.py` 249, `test_13_entity_shapes.py` 258, `test_14_entity_field_discipline.py` 274, `test_15_lifecycle_transitions.py` 226, `test_16_lifecycle_cycles_and_sweeps.py` 254, `test_17_calculation_corners.py` 462, `test_18_validation_corners_catalogue.py` 422, `test_19_validation_corners_channel_and_service.py` 440, `test_20_endpoint_journeys.py` 259, `test_21_error_catalogue.py` 334, `test_22_role_authority.py` 253, `test_23_optimistic_concurrency.py` 235, `test_24_read_your_writes.py` 121.

## Instance → test mapping

- **Queue A (difficulty):** 18/18 instances translated → **85 tests**, every instance ≥2 tests (range 2–14; the two cascades are decomposed hop by hop at 14 and 12).
- **Queue B (corner):** 63/64 non-stub instances translated → **84 tests** (entities 18, state_machines 10, calculations 6, validations 16, endpoints 7, errors 17, rbac 5, cross_cutting 3, consistency_model 2). All 14 `excluded_because:` stubs emitted nothing; their `difficulty_instance` pointers all resolve.

## Skipped

One instance only: **`Corner/calculations/financing_term_36_base_rate_with_probation_addon`**. Its recipe submits a quote while the distributor sits in `PROBATION` and expects HTTP 200 with `provisional_apr_bp == 1590 - 250 + 150 = 1350`. PRD §3.7 and §3.9 (validation rule 54) both state submission demands `AUTHORIZED` and a `PROBATION` distributor is refused with `ERR_DISTRIBUTOR_NOT_AUTHORIZED`, so the asserted success is PRD-contradicted — condition (b) fails. Verified against the PRD; no weakened assertion, xfail or placeholder left behind.

Two individual assertions inside otherwise-kept instances were dropped where the design index contradicted the PRD, both independently confirmed: expiry **does** empty `cert_scopes` (PRD §3.4 "Lapse is quiet"), and the regrant's `QUALITY_HOLD`→`REWORK` move **does** increase `rework_count` by 1 (PRD §3.4 hop one). A handful of smaller asserts were dropped as non-derivable (e.g. whether `component_class_breakdown` groups a count or an amount; the absence of a mutate route for station logs).

## Audit results

- 82 valid `Design:` tags exist in the two indices; 81 are used, 0 invalid, 0 untagged tests, 0 dual-tagged, and in every test the tag is the final docstring line.
- All 169 PRD citations verified as byte-for-byte substrings of `workspace/PRD.md`.
- 0 occurrences of "scaffold", "design index", "§1.8/§1.9" or any yaml filename in the emitted Python.
- All 24 modules import cleanly against the installed framework; pyflakes clean (five unused `pytest` imports stripped).
- No server was started, no pytest run, no process killed; `workspace/implementation/` was never read, listed or written.

### Orchestrator verification
`test_helpers/` and `test_suite/` are both at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md` and `implementation/`. No stray test directory under `workspace/` needed relocation.

## Step 7: Run Tests and Iterate — 2026-09-03T04:00:00.000Z

The artifact is already green. Here is the summary.

## Summary

**Iterations run: 1** (one full 8-round parallel sweep; no fixes were needed, so no second iteration was warranted).

**Sweep result — clean on the first pass:**

| Round | total | passed | failed | errors | skipped |
|---|---|---|---|---|---|
| 1–8 | 169 | 169 | 0 | 0 | 0 |

All 8 rounds were launched concurrently under `setsid nohup` and joined with `wait`; every round ran to completion (~303s each) and produced a complete `results.${i}.json`. The **union of failing tests across all 8 rounds is empty** — no flakiness signal, no timing-sensitive divergence between rounds, no reaping tell (no `Terminated`, no `RemoteDisconnected`/`ConnectionResetError`, no round-boundary die-off).

**Tests deleted:** none. STEP 0 produced an empty union set, so the diagnostic protocol (STEPs 1–3) never engaged — there was no failing test to run a PRD coverage or unique-derivability check against.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Integrity checks run before exiting** (to guard against a green-looking-but-hollow artifact):
- **Collection completeness:** 169 `def test_*` functions are defined across `test_suite/`, and 169 tests were collected and run in every round — nothing was silently dropped from collection, so the green result covers the whole suite.
- **No suppression:** zero `skip` / `xfail` occurrences anywhere in `test_suite/` or `test_helpers/`, corroborated by `skipped == 0` in all 8 result files.
- **Storage discipline:** `workspace/implementation/db.py` holds state purely in Python dicts on a single `Store` instance, with the logical clock initialized to the PRD-mandated `2026-08-01T00:00:00Z`. No SQLite, pickle, shelve, `/tmp` cache, JSON dump, or startup seeding — the only `json.dumps` hit is response serialization in `response.py:56`.

Incidental note for downstream consumers: the per-test status key in `results.*.json` is `status` (values `passed`/`failed`), not `outcome`. A parser keyed on `outcome` silently treats every test as non-passing and reports a full-suite failure union — worth knowing, since that failure mode looks exactly like a catastrophically broken artifact rather than a parser bug.

### Orchestrator independent verification of Step 7
Per prior pipeline experience (a Step 7 subagent once claimed a clean sweep while leaving no results files behind), the orchestrator re-verified rather than trusting the report:
- All 8 `workspace/implementation/results.{1..8}.json` exist on disk, ~55.5 KB each, all timestamped within the same minute.
- Parsed each independently: every round reports `total=169, passed=169, failed=0, errors=0, skipped=0`.
- `grep` for `xfail` / `pytest.mark.skip` across `test_suite/` and `test_helpers/` returned zero matching files.
- `grep -c "def test_"` across `test_suite/*.py` sums to exactly 169, matching the collected count — the green sweep covers the whole suite.

## Step 8: Finalize PRD — SKIPPED — 2026-09-03T04:05:00.000Z

Skip condition met exactly as the skill defines it: Step 7 exited on its first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — zero iterations beyond the baseline. With an empty `<step_7_diff>` there is no PRD-silence or PRD-mismatch site for Step 8 to target, so no subagent was spawned and no `PRD_FINALIZED.md` was produced. Step 9 therefore starts from `workspace/PRD.md`.

## Step 9: Complete PRD — 2026-09-03T05:20:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/` (a single-pass scan of a 3,043-line implementation has previously left `PRD_COMPLETED.md` byte-identical to its source, i.e. the scan never actually ran). Pass 1 created `PRD_COMPLETED.md` from `PRD.md`; passes 2 and 3 edited it in place with the Edit tool, preserving prior passes. Source was `PRD.md` because Step 8 was skipped.

### Pass 1 — app.py, db.py, errors.py, response.py, validate.py, middleware.py, lookup.py, start.sh, routes/{clock,machine_models,rebate_programs,dossiers}.py

531 lines / 124,503 chars → 531 lines / 131,053 chars (+6,550). 14 ambiguity-pins, 1 mismatch-revision.

- §2 intro — insert — ambiguity — trailing slash tolerated on every path (`strict_slashes = False`) — app.py:24
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars, regenerated per response including errors — response.py:21-25
- §2.2 — insert — ambiguity — `api_request_timestamp` is the logical-clock reading, not wall clock, so it repeats across requests without a clock advance — response.py:60-66
- §2.3 — insert — ambiguity — empty-valued `limit`/`offset` treated as absent; non-integer value is `ERR_INVALID_REQUEST`; `offset` unbounded above; over-range offset yields empty page with `has_more` false — validate.py:199-218, 250-252
- §2.3 — insert — ambiguity — filter semantics: optional, empty=absent, conjunctive, bad enum member → 400, string filters exact case-sensitive equality, boolean filters accept true/false/1/0 any case — validate.py:221-247
- §2.3 — insert — ambiguity — all orderings break `created_at` ties on write order — db.py:62-71
- §2.4 — insert — ambiguity — lenient ISO 8601 instant parsing (`Z`, offset, offset-less→UTC, normalized to UTC); date-typed fields are any non-empty string stored verbatim — validate.py:44-56, 163-169
- §2.5 — insert — ambiguity — `to_iso8601` required; clock accepts any instant including backwards, no monotonicity, both sweeps run every call — routes/clock.py:13-15
- §2.6 — revise — mismatch — PRD said percentage/decimal inputs carry "exactly two decimal places"; impl accepts **no more than** the declared scale and normalizes (`7.2`→`7.20`), rejects excess scale/strings/booleans, and serializes decimals as bare JSON numbers at full stored scale — validate.py:114-139, response.py:50-57
- §2.8 rule 3 — insert — ambiguity — absent/empty body = empty object; non-object JSON body is a violation; explicit `null` counts as omitted; integer fields accept zero-fraction numbers, reject booleans — validate.py:31-41, 63-65, 96-112
- §2.12 — insert — ambiguity — free-text `reason` 1–500 chars, `note` 1–1000 chars, validated when present, never stored or echoed; probation `reason` is the enum instead — routes/machine_models.py:118, routes/dossiers.py:96, routes/distributors.py:140
- §3.2 — insert — ambiguity — `rebate_cap_cents` < `rebate_base_cents` is `ERR_INVALID_REQUEST`/400, ranked with rule 3 ahead of interval/window/uniqueness — routes/rebate_programs.py:39-41
- §3.3 — insert — ambiguity — lifecycle `reason` validated but not stored; a RELEASE leaves `suspended_reason` and both rebate fields untouched — routes/machine_models.py:118, 121-126
- §3.3 — insert — ambiguity — resurvey submission leaves `certified_at`, `resurvey_count`, `qualified_program_codes` and `rebate_amount_cents` as the breach left them — routes/dossiers.py:152-162
- §3.9 — insert — ambiguity — warranty-analysis breakdown shape: object keyed only by classes present (absent, not zero), each value `{claim_count, covered_amount_total_cents}` with voided excluded, keys in claim-filing order; `duty_cycle_class` filter narrows every figure — routes/machine_models.py:151-184
- §5 intro — insert — ambiguity — unknown path → `ERR_INVALID_REQUEST` 404, bad method → 405, unexpected condition → 500, all in the standard error envelope — app.py:33-54

Verified needing no change: errors.py status map matches the §5 table entry for entry; model-creation (42→48→49) and program-creation (3→44→47→48) check order matches §2.8; clock sweep predicates and counters match §2.5.

### Pass 2 — routes/{service_parts,assembly_stations,technicians,build_orders}.py

131,053 → 132,622 chars (+1,569). 8 ambiguity-pins, 0 mismatch-revisions — no behavior in these four files contradicted PRD prose; every gap was silence.

- §3.1 — insert — ambiguity — the `fits_max_capacity_lb < fits_min_capacity_lb` rejection is ranked with §2.8 rule 3, ahead of an unresolvable `supersedes_part_id` (404) and a duplicate `part_number` (409) — routes/service_parts.py:40-49
- §3.9 — insert — ambiguity — `delta_qty` is a required integer with no bound of its own; a receipt, a shrinkage and an explicit `0` are all accepted — routes/service_parts.py:99
- §3.9 — insert — ambiguity — the part's `version` advances on every accepted adjustment including a `0` delta and one leaving `stock_state` unchanged; `reserved_qty` is never touched — routes/service_parts.py:106-108
- §3.4 — insert — ambiguity — an `employer`/`distributor_id` pairing violation is `ERR_INVALID_REQUEST` and precedes FK resolution, so a `FACTORY` technician with an unresolvable `distributor_id` reports 400 not `ERR_DISTRIBUTOR_NOT_FOUND` — routes/technicians.py:31-39
- §3.4 — insert — ambiguity — a field the submitted `action` does not use is ignored without validation: `scopes`/`expires_on` on a revocation, `reason` on a grant or renewal — routes/technicians.py:92-100
- §3.4 — insert — ambiguity — `cert_expires_on` is left as it stood rather than cleared on revocation — routes/technicians.py:121-126
- §3.5 — insert — ambiguity — state and model certification are the only release gates: `integrity_hold` is neither consulted nor cleared, and `rework_count`/`labor_minutes_total`/`station_pass_count`/`scrap_reason` are preserved — routes/build_orders.py:92-104
- §3.6 — insert — ambiguity — a `defect_code` supplied with an `APPROVE` is accepted, validated, and never stored or echoed — routes/build_orders.py:111,130-137
- §3.5 — insert — ambiguity — a station-log creation returns the newly created log rather than the parent unit — routes/build_orders.py:256

Fully pinned already: `assembly_stations.py` in its entirety; all list orderings/filters/role sets; the station-log check order (10→19→22→26→36→37→39→40→43→44→45→46), the scope check keyed on the *station's* `station_type` while the preload requirement is keyed on the *submitted* one, closed-interval station contention vs half-open technician contention, floored `labor_minutes`, and the FAIL→`REWORK`→scrap-over-ceiling chain with its two version bumps.

### Pass 3 — routes/{distributors,quotes,warranty_claims}.py, services/{calc,cascades}.py

132,622 → 138,515 chars (+5,893). 10 ambiguity-pins, 4 mismatch-revisions.

- §2.4 — revise — **mismatch** — PRD claimed a date-typed input "is stored and echoed back verbatim"; impl validates `completed_on` as a non-empty string then discards it. Also pinned that it is the only date-typed input in the API — routes/distributors.py:100
- §2.11 — insert — ambiguity — a cascade's recomputation of a parent's derived counters bumps the parent only when a value actually changed; one parent may be touched twice in a request, once per touch — services/cascades.py:63-73,80-82
- §3.4 — revise — ambiguity — revocation-cascade enumeration was missing `PLANNED` and `REWORK` units: they keep their state and take only the flag; an already-flagged unit is re-flagged and version-bumped again — services/cascades.py:149-154
- §3.6 — insert — ambiguity — hop four gates the rest: with no dossier in `CERTIFIED` the cascade stops there and hops five and six never run — services/cascades.py:112-115
- §3.6 — insert — ambiguity — hop five runs only when the model is `RELEASED` or `CERTIFIED`; an already-`SUSPENDED` model ends the cascade at hop four — services/cascades.py:123-125
- §3.7 — revise — ambiguity — a `reason` on `REINSTATE` is never read and never validated; a termination leaves `probation_reason` exactly as it stood — routes/distributors.py:136-140,157-161
- §3.7 — revise — **mismatch** — the 150 bp probation add-on cannot reach the provisional computation (submission demands `AUTHORIZED`); it can only land on the final approval-time computation — services/calc.py:120-124, routes/quotes.py:61-69
- §3.8 — insert — ambiguity — the quoted model's `certification_state` is not consulted on line creation; a `DRAFT` or `SUSPENDED` model may be quoted — routes/quotes.py:167-179
- §3.8 — revise — ambiguity — quote-line read/list are not ownership-scoped; the quote-list scope is a conjunctive filter, so a `Distributor` filtering on someone else's `distributor_id` gets an empty page, not `ERR_OWNERSHIP_VIOLATION` — routes/quotes.py:144-147,216-234
- §3.8 — revise — **mismatch** — submission gate order: PRD listed `ERR_DISTRIBUTOR_NOT_AUTHORIZED` ahead of `ERR_QUOTE_HAS_NO_LINES` while claiming to follow §2.8, which ranks them the other way (as impl does); also pinned the down-payment check as ranked below all three despite reporting `ERR_INVALID_REQUEST`, and corrected the impossible "placed on probation between two submissions sees a worse rate" sentence — routes/quotes.py:246-255
- §3.8 — revise — ambiguity — `verified_credit_score` on `DECLINE`/`REQUEST_REVISION` is range-checked then discarded; a revision request leaves `origination_fee_cents` and `financed_principal_cents` at the earlier submission's figures — routes/quotes.py:268-287
- §3.9 — insert — ambiguity — a `denial_reason` on an `APPROVE` is still validated against the three-member enum (so `NONE` there is `ERR_INVALID_REQUEST`) and then discarded — routes/warranty_claims.py:132-133
- §3.9 — revise — ambiguity — on approval the stock re-projection runs before the money moves, and the claiming distributor's row is version-bumped unconditionally, so its `version` advances by 2 when the backorder cascade also blocked one of its own claims — routes/warranty_claims.py:183-190
- §3.9 — revise — **mismatch** — "unblocking is conjunctive" over-promised: release is keyed on the claim's recorded `block_reason` (regrant only sees `BUILD_INTEGRITY_HOLD`, re-projection only sees `PART_BACKORDERED`), so a claim stays blocked when the obstacle its `block_reason` names cleared first — services/cascades.py:211-213,244-251

### Step 9 totals

`PRD.md` 531 lines / 124,503 chars → `PRD_COMPLETED.md` 531 lines / 138,515 chars: **+14,012 chars, 0 lines** (every edit in-paragraph; no new sections or paragraphs). **24 ambiguity-pins, 5 mismatch-revisions** across 37 surgical Edit calls.

### Orchestrator independent verification of Step 9
- `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD.md` — the scan genuinely ran. `diff` reports 72 changed lines (36 replaced line-pairs).
- Sections §1–§5 present and in order (offsets 3 / 11 / 218 / 418 / and the §5 table).
- §4 endpoint table re-counted independently: **52 rows**, matching the 52 registered Flask routes.
- File ends on the final `ERR_STOCK_ADJUSTMENT_NEGATIVE | 422` row — a real section boundary, no truncation.
- All 8 `results.{1..8}.json` from the final green sweep remain in `workspace/implementation/`.

## Pipeline complete — 2026-09-03T05:25:00.000Z

All nine steps finished. Step 8 skipped by its documented skip condition. Final artifact: 169 tests, 8/8 sweep rounds at 169/169.
