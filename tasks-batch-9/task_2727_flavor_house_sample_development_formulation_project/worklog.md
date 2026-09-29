# Worklog — task_2727_flavor_house_sample_development_formulation_project

## Step 1: Create task directory — 2026-09-04T12:30:00.000Z

Created `tasks/task_2727_flavor_house_sample_development_formulation_project/` and `.../workspace/` at the pre-assigned path. No index auto-allocation performed (index fixed by scenario number 2727).

## Step 2: Generate scaffold — 2026-09-04T13:54:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Output** — `/home/ubuntu/github/CodingPRD/tasks/task_2727_flavor_house_sample_development_formulation_project/`

| file | lines | contents |
|---|---|---|
| `SCAFFOLD.yaml` | 3055 | §1.0–§1.7: 15 entities, 69 endpoints, 61 errors, 6 roles, 2 concurrency rules; no `scaffold_difficulty_design` / `scaffold_corner_design` key |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2037 | single key `scaffold_difficulty_design`, 21 instances across 9 difficulty rules |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3838 | single key `scaffold_corner_design`, 81 instances (62 with full `test_recipe`, 19 `excluded_because` stubs) over all 9 guide sections |

Linter verdict (verbatim, final run):

```
Coverage
  §1.5 endpoints declared:    69
  §1.1 entities declared:     15
  §1.8 instances scanned:     21
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  980

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Work completed this session (the corner-design file's second half): `endpoints` finished (component delete reverting COSTED→DRAFT, delete on APPROVED rejected, pilot-run signed yield variance −2.00 with the 403000-cent batch total), then whole new `errors` (15-code path-param not-found sweep, 7-code body-FK sweep, repeat-action `*_STATE_INVALID` trio, `ERR_FORMULA_NOT_REVISABLE`, `ERR_SUB_FORMULA_NOT_COSTED`), `rbac` (401 header tier, 5 cross-role 403s, two segregation-of-duties instances, six-role shared reads), `complexity_layers` (both OCC rules, brief version walk 1→5, `ERR_PINNED_FORMULA_STALE` after a reprice plus the fresh-batch success at 445000, derived-field reconciliation walk, two stubs deferring to §1.8) and `consistency_model` (immediate visibility in the write response; reprice fan-out readable on the next call).

Verification beyond the linter: 102 instance names unique across both design files, all 61 declared error ids triggered by at least one instance, every `excluded_because.difficulty_instance` resolves to a real §1.8 instance, no stub carries a `test_recipe`, no instance carries a key outside the §1.9 schema (one stray `setup:` and one stray `setup_note:` were caught and removed), every `${var}` bound by an earlier `captures:`, and none of the forbidden concurrency vocabulary appears. Two arithmetic corrections were made while writing: `firm_cost_in_use` at 2500 cents/kg is 24620 (not 24610), and the shipment/lot-mass instances were ordered so the intended lower-priority error is the one observed.

## Step 3: Copy shared files — 2026-09-04T13:54:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T14:10:00.000Z

All checks pass. The PRD is complete.

**Output:** `workspace/PRD.md` — 451 lines, 96,794 bytes, built with 10 incremental appends (no single-Write truncation). Ends cleanly at a real section boundary: the last row of the §5 error table, `| \`ERR_COST_IN_USE_CAP_EXCEEDED\` | 422 |`.

**Structure:** §1 Introduction; §2 Global Specifications (11 subsections: RBAC, response envelope emitted byte-verbatim from `section-2.2-response-structure.md`, pagination, identity/audit/logical clock, path resolution and reference integrity, money/mass/rounding, version pinning and OCC, segregation of duties, confidentiality tiers and formula disclosure, cascade propagation and reconciliation, and an 18-item rejection-priority ladder); §3 Business Logic in 9 workflow subsections (brief intake → raw-material catalogue → component graph → bench costing → technical approval and revision lineage → compounding/QC/retention → application testing → shipment and regulatory packet → scale-up, forecasting and closure); §4 a 69-row endpoint table; §5 a 61-row error catalogue.

**Hard Contract reports**

- **Contract 1 — Field-Name Coverage: PASS.** 124/124 `entities[].fields[].name` present verbatim in backticks, 0 missing. 84/84 distinct `request_body`/`query_params` identifiers present, 0 missing. 15/15 path parameters present as bare backticked tokens (enumerated in §2.5 alongside their 15 corresponding not-found error IDs, since §4's table only contains full path strings). 61/61 error IDs present.
- **Contract 2 — Rule Coverage: PASS.** All 6 high-risk categories covered: validation priority ordering (§2.11 ladder, priorities 10→82 collapsed into 18 ordered tiers); both `concurrency_rules` with their write endpoints named explicitly (`expected_formula_version` on `POST /formulas/{formula_id}/revisions` → `ERR_STALE_FORMULA_VERSION` 412; `expected_brief_version` on `POST /commercialization-forecasts` → `ERR_STALE_BRIEF_VERSION` 412); cross-entity cascade side effects (rework cascade, mass-ledger reconciliation, slot occupancy release, `CONSUMED → RELEASED` restoration); all `applies_to` scopes; field-level structured content; sibling-branch symmetry (dual-variant `formula_cost_in_use` and `forecast_value`, the `BLOCKED`/`DRAFT` packet-assembly paths). Tail coverage complete: all 39 state/enum values appear as bare backticked tokens, all 11 calculations, all 35 validation conditions, all endpoint side effects.
- **Contract 3 — §3 Path Purity: PASS.** 1,077 backticked tokens in §3; 0 begin with `/`, 0 are a bare HTTP method, 0 combine method+path.

**Fuzzy-word scan:** clean.

**Constraints honoured:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task directory was read.

Orchestrator truncation guard: verified independently — `wc -c` = 97122, tail ends at the final `ERR_COST_IN_USE_CAP_EXCEEDED` table row (a real section boundary), 5 top-level `##` sections present. Not truncated; no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T15:00:00.000Z

(Launched concurrently with Step 5 in a single orchestrator message; Step 6 returned first, so its entry is recorded here ahead of Step 5's.)

Done. Second smoke pass over the cascade/corner paths came back clean, the server is shut down (ports 41777 and 43219 both freed by exact PID), and `__pycache__` has been removed.

## One real bug found and fixed during this pass
`start.sh` was mode `0644` — `./start.sh` failed with exit 126 (Permission denied). Since the harness relaunches the server via `start.sh` before every test, this would have failed the entire suite. Now `0755` (`-rwxrwxr-x`) and verified booting.

## Files written (all under `workspace/implementation/`)
3569 lines of Python + a 10-line `start.sh` + 1-line `requirements.txt`.

| File | Lines |
|---|---|
`app.py` | 59
`db.py` | 158
`errors.py` | 92
`middleware.py` | 33
`response.py` | 71
`validate.py` | 176
`constants.py` | 109
`serializers.py` | 276
`services/graph.py` | 134
`services/costing.py` | 164
`services/ledger.py` | 160
`services/cascade.py` | 314
`routes/common.py` | 26
`routes/briefs.py` | 201
`routes/materials.py` | 187
`routes/formulas.py` | 448
`routes/lots.py` | 266
`routes/tests.py` | 204
`routes/shipments.py` | 203
`routes/batches.py` | 137
`routes/commercial.py` | 151
`routes/__init__.py`, `services/__init__.py` | 0
`start.sh` | 10
`requirements.txt` | 1

`start.sh` reads `$PORT`, `cd`s to its own directory, installs Flask only if missing (to avoid pip contention across the 8 concurrent per-test reboots), and `exec`s `python3 app.py` in the foreground on `0.0.0.0`. Storage is in-memory dicts only, nothing seeded.

## Coverage (machine-verified, not eyeballed)
- **Endpoints: 69/69 exact.** Diffed the PRD §4 table against `app.url_map`: `missing: []`, `extra: []`.
- **Errors: 61/61.** Every `ERR_*` in the PRD is in `errors.ERROR_HTTP` with its HTTP status, no impl-only extras, and every one is actually raised from `routes/`, `services/`, `validate.py` or `middleware.py` — no dead entries.

## Smoke evidence from this pass
Clarification ladder 1/2/3 then `REJECTED` + `CLARIFICATION_EXHAUSTED` without incrementing past 3; `ERR_SUB_FORMULA_NOT_COSTED` before sub-formula costing then bench roll-up 27500 exactly; self- and transitive `ERR_FORMULA_CYCLE`; component DELETE → 204 with `COSTED → DRAFT` fallback nulling costs/claims and clearing `contribution_cents`; the three submission gates (`ERR_CLAIM_UNSUBSTANTIATED`, `ERR_COST_IN_USE_CAP_EXCEEDED`, `ERR_ALLERGEN_EXCLUSION_BREACH`); the full failed-application-test fan-out in one shot (formula `REWORK_REQUIRED`/`APPLICATION_TEST_FAILURE`, lot `HELD`, shipment `BLOCKED`/`LOT_HELD`, batch `CANCELLED`/`FORMULA_REWORK`, forecast `AT_RISK` tf 0.55); brief close LOST → shipment `CANCELLED`/`BRIEF_CLOSED_LOST` with grams returned, formula `ARCHIVED`, forecast `LAPSED`; `ERR_DOC_PACKET_INCOMPLETE`; `ERR_PACKET_EXPIRED`; `ERR_SUBSTANTIATION_REVOKED` at dispatch; re-verify → doc `STALE` → `ERR_PINNED_DOC_STALE`; grant `ACTIVE`→`EXPIRED` at the boundary and `ERR_DISCLOSURE_GRANT_EXPIRED`.

## PRD ambiguities resolved
- **§2.11's 18-rung ladder outranks §3.x narration** wherever they disagree: `ERR_BRIEF_NOT_ACCEPTED` before `ERR_SEGREGATION_OF_DUTIES` on formula decision; `ERR_SUB_FORMULA_NOT_COSTED` before `ERR_FORMULA_NO_COMPONENTS`/`ERR_WEIGHT_SUM_INVALID` on costing; `ERR_CABINET_CAPACITY_EXCEEDED` before `ERR_INVALID_INTERVAL`/`ERR_RETENTION_PERIOD_TOO_SHORT` on retention creation.
- **Two clocks.** `created_at`/`updated_at` come from a strictly monotonic ms-truncated wall clock so `created_at ASC` equals insertion order; the logical clock governs only expiry/interval/window/grant evaluation and explicitly system-stamped domain fields (`verified_at`, `withdrawn_at`, `verdict_recorded_at`, `generated_at`, `dispatched_at`, `closed_at`).
- **No version bump for derived fields** (`claim_status`, `verified_claim_types`, `component_count`, `total_weight_pct`, `allocated_g`/`available_g`, `slots_available`, grant `status`) — all re-derived on read. Component add/delete bumps the formula version only when the `COSTED`/`REWORK_REQUIRED → DRAFT` fallback fires.
- **`BATCH_SUPERSEDED` is deliberately unreachable.** SCAFFOLD's `POST /scale-up-batches` side-effects list only creation-plus-pin, whereas the forecast endpoint documents its supersession cascade explicitly — so a second batch on the same formula leaves earlier batches untouched.
- **Composition redaction.** Full view for TIER_1 or a presented FULL grant; a REDACTED grant nulls `raw_material_id`/`sub_formula_id`/`weight_pct`/`contribution_cents` and adds `weight_bucket` (0-1/1-5/5-10/10-25/25-50/50-100 — the PRD never defines a bucket scheme); `disclose_full=true` without a FULL grant is `ERR_REDACTION_LEVEL_INSUFFICIENT` (including TIER_1-with-no-grant, read literally); an unknown `grant_id` is `ERR_GRANT_NOT_FOUND` at TIER_1 but `ERR_IP_TIER_FORBIDDEN` at TIER_2/3; a presented expired grant is rejected at any tier; the composition `meta` carries no pagination fields.
- **Re-costing is DRAFT-only** — verified verbatim in §3.4, so a later certificate verification does *not* retroactively flip a `COSTED` formula's eligibility flags; §3.2 confirms verification recomputes only the material's derived fields and staleifies documents.
- **Packet re-assembly is `{DRAFT, BLOCKED}` only** (SCAFFOLD line 1205 confirms), so a `PACKET_ASSEMBLED` shipment whose docs went `STALE` via a non-required-claim revocation reaches `PINNED` again only through the `BLOCKED` remediation loop; assembling from `PACKET_ASSEMBLED` returns `ERR_SHIPMENT_STATE_INVALID` (409).
- **`ERR_DOC_PACKET_INCOMPLETE`** requires a candidate certificate on *every* transitive leaf material for each certificate-backed required type.
- A revision successor **inherits the predecessor's `confidentiality_tier`** (unspecified in the PRD). Unconstrained free-text fields are validated as strings with no length bounds; `storage_temp_c` and `measured_yield_kg` accept any precision within their declared ranges; Decimals serialise as JSON numbers. Formula `decision_note` and lot `qc_note` are accepted-and-ignored (no such entity fields exist).

## Step 5: Generate unit tests — 2026-09-04T15:45:00.000Z

(Launched concurrently with Step 6; returned second. Orchestrator verified both trees are at the task root — `workspace/test_helpers` and `workspace/test_suite` do not exist.)

Step 5 is complete. Both output trees are under the task root (nothing was written to `workspace/`, `worklog.md` was not touched, no servers were started or killed).

## Files written

`test_helpers/` — 2,579 lines
| file | lines |
|---|---|
| `__init__.py` | 25 |
| `api_client.py` | 299 |
| `api_errors.py` | 136 |
| `assertions.py` | 343 |
| `constants.py` | 108 |
| `factories.py` | 340 |
| `fixtures.py` | 737 |
| `test_users.py` | 111 |
| `types.py` | 480 |

`test_suite/` — 4,645 lines, **123 test functions** across 17 files plus `conftest.py` (73)
`test_01` 199/8 · `test_02` 173/7 · `test_03` 213/6 · `test_04` 157/6 · `test_05` 226/8 · `test_06` 362/10 · `test_07` 290/9 · `test_08` 215/7 · `test_09` 352/12 · `test_10` 325/9 · `test_11` 227/5 · `test_12` 406/11 · `test_13` 326/8 · `test_14` 336/5 · `test_15` 266/5 · `test_16` 328/5 · `test_17` 171/2 (lines/tests).

## Instance coverage — 83/83 live instances, zero skips

- **§1.8 queue A (Difficulty): 21/21** live instances translated (0 stubs in that file).
- **§1.9 queue B (Corner): 62/62** live instances translated; the 19 instances carrying `excluded_because` were correctly left alone. By section: entities 12, state_machines 9, calculations 5, validations 11, endpoints 8, errors 5, rbac 5, complexity_layers 5, consistency_model 2.
- Every test carries exactly one `Design:` line as the final docstring line; a mechanical audit found 0 untagged, 0 dual-tagged, 0 dangling and 0 stub-pointing tags, and 0 `skip`/`xfail` markers (`@pytest.mark` appears nowhere in the suite).

## Verification performed

- `python3 -m pyflakes` clean across all 18 suite files and every helper except `test_helpers/__init__.py`, whose warnings are its deliberate `# noqa: F401` re-exports. Fixed two real dead imports found this pass (`typing.List` in `factories.py`, `DIRECTOR_SECOND` in `fixtures.py`).
- `compileall` clean; `__pycache__` removed afterwards.
- **PRD-citation audit**: extracted all 238 double-quoted spans from test docstrings and matched them against `workspace/PRD.md` after whitespace/dash/arrow normalisation. Found and repaired **15 paraphrased citations** in test_04/05/06/08/10/15/16 (e.g. "the owning formula must still be `APPROVED`" → "its formula must still be `APPROVED`"; "the entity's own state precondition is evaluated before any business or fiscal rule" → the real §2.11 sentence "own-state outranks every business rule below it, an already-approved formula asked to submit reports a state error rather than a cost-cap error"; "the earliest `valid_until` among the pinned certificate-backed records" → "set to the earliest `pinned_valid_until` across the certificate-backed documents"; "incremented by 1 on every successful state-changing operation" → §2.4's actual "increments by 1 on every mutation of that resource"). The 4 residual reports are artifacts of the regex pairing one quote's closing mark with the next quote's opening mark, not real citations.
- **Field-name audit**: every string subscript key used anywhere in the suite/helpers now resolves to a name present in `PRD.md` or `SCAFFOLD.yaml`, apart from three local fixture-dict keys.

## Design/PRD conflicts adjudicated

1. `errors` recipes assert `SampleLot.available_mass_g`; PRD §3.6 names the field `available_g`. **PRD wins** — `available_g` used throughout.
2. `complexity_layers/stale_expected_brief_version...` asserts `CommercializationForecast.base_annual_value_cents == 5000000`, but that field exists in **neither** the PRD nor SCAFFOLD's `CommercializationForecast` field list (which is `brief_id, annual_volume_kg, unit_price_cents_per_kg, pinned_brief_version, variant_applied, stage_probability, technical_factor, weighted_annual_value_cents, status`). That single unsupported assertion was dropped and replaced with PRD-derivable ones on the stored inputs plus `stage_probability` 0.45 / `technical_factor` 0.55; the instance's actual asserted outcome (412 `ERR_STALE_BRIEF_VERSION`, then a 201 `ACTIVE` forecast at 1,237,500 with the brief still at version 3) is fully PRD-derived, so the instance was kept rather than skipped.
3. Carried from earlier passes: component deletion is 204-no-body (a `delete_component` helper, never `get_success_data`); error ids live at `data.error_id`; the document field is `doc_type`, not `document_type`.

All money and mass literals are JSON ints, and every ISO-8601 comparison goes through `canonical_instant`/`assert_instant_equals` in the assertion layer rather than asserting raw sub-second width.

## Step 7: Run tests and iterate — 2026-09-04T16:30:00.000Z

All 8 parallel rounds green at 123/123.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each, 123 tests, per-test-server isolation).

- Iteration 1: 121/123 in **all 8** rounds — the same 2 tests failed deterministically in every round (no flakiness anywhere else in the suite).
- Iteration 2 (after fix): **123/123 in all 8 rounds.** Test count unchanged at 123 — nothing was deleted or skipped.

**Tests deleted:** none. Both failures were the *same* uncovered assertion inside otherwise well-covered tests, so STEP 1c (partial-coverage split) applied: keep the covered assertions, remove the uncovered one.

**Fixes applied to `test_suite/`** — `test_suite/test_09_entity_shapes_and_reference_integrity.py`:

1. `test_brief_creation_answers_the_standard_envelope_with_system_defaults` — dropped `assert_instant_equals(brief["created_at"], INITIAL_CLOCK, "created_at")`. **DEFAULT-VALUE / SOURCE SILENCE:** PRD mentions `created_at` in exactly two places (§2.4: it exists alongside `updated_at`/`version`; and it is "ISO 8601 UTC ... with exactly three fractional-second digits"). No sentence ties `created_at` to the logical clock — §2.4's clock scope is the closed list "every expiry comparison, retention interval, rig occupation window, certificate validity check and disclosure-grant lifetime", and every field PRD *does* stamp from the clock is named explicitly (`verified_at`, `withdrawn_at`, `verdict_recorded_at`, `generated_at`, `dispatched_at`, `closed_at`). All the test's other assertions (envelope keys, `DRAFT`, `clarification_round_count` 0, the five nulls, `version` 1) are verbatim-covered and were kept.
2. `test_raw_material_system_fields_input_ignored` — replaced the same clock assertion with `assert material["created_at"] != "1999-01-01T00:00:00Z"`, which preserves the test's actual stated purpose (a client-supplied `created_at` is not honoured — `created_at` is not among §3.2's declared material inputs) without importing the un-derivable logical-clock claim. Its `id`/`version`/`claim_status`/`verified_claim_types` assertions are untouched.
3. Dropped the now-unused `assert_instant_equals` / `INITIAL_CLOCK` imports.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — no implementation defect was found.

**Key finding worth recording:** the logical-clock reading of `created_at` is not merely unstated, it is *contradicted* by the PRD's own rules. PRD derives `sequence_no`, `iteration_no` and the lot sequence position as "one more than the number of ... with an earlier creation timestamp", breaks packet-pin ties "by ascending creation timestamp", processes reprice cascades "in ascending order of the formulas' creation timestamps", and sorts every list by creation timestamp ascending. Since the clock only moves when a client moves it, sourcing `created_at` from the clock would give every record created at one clock position an identical timestamp, collapsing all of those counters to 1. The implementation (`workspace/implementation/db.py`, strictly monotonic millisecond wall-clock stamp for `created_at`/`updated_at`, logical clock for expiry comparisons and the explicitly-named stamped fields) is the PRD-faithful reading, and the 121 other passing tests — including the `sequence_no == 3` and `[1, 2]` ordering tests — depend on it.

**Orchestrator verification of sweep artifacts:** independently re-read all 8 `workspace/implementation/results.$i.json` — every file parses and reports `passed=123 / total=123 / failed=0`. The clean sweep is real, not asserted.

**Step 8 decision:** Step 8 is NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes; here there were 2 `test_suite/` assertion corrections. Since there were 0 `implementation/` fixes, a byte-identical `PRD_FINALIZED.md` is a legitimate outcome — the Step 7 diff records a PRD silence about `created_at`'s source that Step 8 may pin, but no impl/PRD behavioural divergence.

## Step 8: Finalize PRD — 2026-09-04T16:45:00.000Z

PRD_FINALIZED.md produced at `workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md 451 lines, PRD_FINALIZED.md 451 lines (0% line delta; 2 lines revised in place, no new sections).

**Changes (both trace to Step 7 items 1–3, the `created_at` clock-source silence):**
- §2.4 (line 83) — revise/insert — after the "exactly three fractional-second digits" sentence, pinned that `created_at`/`updated_at` are stamped from the server's own real time at the instant of the write (not the logical clock, and unaffected by setting the clock), that stamps are handed out in a strictly increasing sequence shared by all entity types so no two records share a `created_at` and creation-timestamp ordering reproduces creation order, that a new record's two stamps hold the same instant, and that neither field is a client input (a body-supplied value is disregarded) — `implementation/db.py:64-78` (`stamp`), `db.py:118-126` (`base_entity`), `db.py:129-132` (`touch`), `db.py:135-136` (`by_creation`).
- §2.4 (line 85) — revise — opening sentence "Time in this system is not wall-clock time." became "Setting aside the `created_at` and `updated_at` audit stamps just described, the time that governs behaviour in this system is not wall-clock time." so the logical-clock paragraph no longer contradicts the new stamp rule — `implementation/db.py:16-18, 52-57`, `routes/commercial.py:145-151`.

**Per-edit pre-edit search log**

Edit 1 — (a) Subject: source, uniqueness and client-writability of the `created_at`/`updated_at` audit stamps on every entity. (b) Enumerated/read: `db.py` in full (`stamp`, `base_entity`, `touch`, `by_creation`, `iso`, `LOGICAL_CLOCK_INITIAL`, `now_logical`/`set_logical`); grep of `created_at|updated_at|stamp()` across all of `implementation/` — only `serializers.py:9-10` (render), `db.py`, and `services/cascade.py:250` (packet-pin tie-break `valid_until, created_at, _ord`); all 17 `base_entity()` callsites (`routes/{materials,tests,lots,commercial,batches,briefs,formulas,shipments}.py`, `services/cascade.py:287`) confirming all 15 entity types share one stamp source; every `now_logical()` callsite (`routes/lots.py:261` `withdrawn_at`, `routes/tests.py:190` `verdict_recorded_at`, `routes/materials.py:165` `verified_at`, `routes/shipments.py:137,156`, `routes/briefs.py:188,196` `closed_at`, `services/{ledger,cascade,graph}.py`, `serializers.py:64,268`) confirming the clock is used only for the explicitly-named stamped fields and derived expiry checks; `validate.py` and `routes/materials.py:30-51` confirming no strict-unknown-key rejection, so a supplied `created_at` is silently ignored rather than an error; `response.py:17-24` confirming `api_request_timestamp` is also real time. (c) Adjustment: dropped an initial "the one exception to the logical clock" phrasing to "do not come from the logical clock", because `response.py`'s envelope timestamp is a second real-time source and an exhaustive-exception claim would have been a new false universal. Scoped the ignore-on-input claim to request bodies (query strings carry `*_id` filters, a different subject).

Edit 2 — (a) Subject: the blanket "time is not wall-clock time" claim, now that two audit fields are wall-clock. (b) Enumerated/read: `db.py:16-18` (initial clock never falls back to host time), `db.py:52-57`, `routes/commercial.py:143-151` (clock-set endpoint mutates no record, so stamps genuinely do not move), all `now_logical()` sites above, `response.py:17-20`. (c) Adjustment: used "Setting aside … the time that governs behaviour" instead of "Apart from … time in this system", so the sentence is not readable as an exhaustive list of wall-clock-sourced values (the envelope timestamp is another); the "must never fall back to the host's real time" clause was left verbatim since it constrains the logical clock only.

No `implementation/`, `test_suite/` or `test_helpers/` files were modified; worklog.md was not read or touched.

**Orchestrator verification:** `PRD_FINALIZED.md` exists and is NOT byte-identical to `PRD.md` (diff confirms the two §2.4 line revisions).

## Step 9: Complete PRD — 2026-09-04T18:15:00.000Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 created it by `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying and edited in place). Partitioning was chosen because the implementation is 3569 lines across 21 modules and the PRD is 98KB — a single agent cannot hold both and still reason carefully about every behavior.

### Pass 1 — global/cross-cutting layer (`app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `validate.py`, `constants.py`, `serializers.py`, `routes/common.py`)

`PRD_COMPLETED.md` created by `cp` from `PRD_FINALIZED.md`. 451/98070 → 455/107114 (+4 lines from two new paragraphs inside existing §2.3 and §2.6; no new sections). **13 ambiguity-pins, 0 mismatch-revisions** — §5's 61 error rows verified programmatically against `errors.ERROR_HTTP` with zero status divergences.

- §2.1 — insert — ambiguity — role name comparison exact/case-sensitive, empty header counts as absent, `X-User-ID` accepts any non-empty string — `middleware.py:25-29`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly twenty `A`–`Z`/`0`–`9` chars, regenerated per response including errors — `response.py:10,13-14`
- §2.2 — insert — ambiguity — the four pagination keys are the only `meta` additions; the composition read is an array response with no pagination keys; the 204 carries no envelope; all other responses are `application/json` — `response.py:23-24,45-46,59-62`
- §2.3 — insert — ambiguity — `limit`/`offset` must be plain signed decimal integer literals, so `""`/`abc`/`10.5` are `ERR_INVALID_REQUEST` rather than defaulted; `offset` past `total_count` is legal — `validate.py:12,144-164`
- §2.3 — insert — ambiguity — no list endpoint departs from creation-ascending order and none accepts a sort/order parameter — `routes/common.py:16-20`, `db.py:135-136`
- §2.3 — insert — ambiguity — `has_more` formula spelled out; `limit`/`offset` echoed as effective values — `response.py:49-56`
- §2.3 (new ¶) — insert — ambiguity — filter convention: omitted = unrestricted, exact case-sensitive equality, conjunctive; an out-of-enum or dangling-id list filter yields 200 + empty page + `total_count` 0 rather than 400/404; `grant_id` on the composition read explicitly excluded — `validate.py:172-176`, `routes/common.py:23-26`
- §2.4 — insert — ambiguity — `id` is a random v4 UUID, lower-case hyphenated 8-4-4-4-12, never a client input; every timestamp field renders `…ss.sssZ` truncating finer precision; unset timestamps render JSON `null`; no declared field is ever omitted — `db.py:60-61,81-86`, `serializers.py:7-12`
- §2.4 — revise (wording) — ambiguity — "These two audit stamps" → "The `created_at` and `updated_at` audit stamps" to keep the antecedent correct after the insert above
- §2.4 — insert — ambiguity — clock capability is `POST /_clock/set_current_utc`, `current_utc` mandatory ISO 8601, may move backwards, answers 200 with empty `data`, is not an entity mutation — `routes/commercial.py:145-151`, `db.py:56-57`
- §2.6 — insert — ambiguity — fewer decimal places than the pin is accepted and held at the pinned scale — `validate.py:85-96`
- §2.6 (new ¶) — insert — ambiguity — numbers travel as JSON numbers only: numeric strings, booleans, `NaN`/`Infinity` are `ERR_INVALID_REQUEST`; integer fields reject `5.0`; decimal fields accept bare `5`; decimals emitted shortest-form (`12.5000` → `12.5`), never as strings — `validate.py:61-96`, `db.py:152-158`
- §2.9 — insert — ambiguity — a `grant_id` naming no stored grant is `ERR_IP_TIER_FORBIDDEN` on TIER_2/TIER_3 but `ERR_GRANT_NOT_FOUND` on TIER_1; a resolvable grant still applies its live-ness and `redaction_level` on a TIER_1 read — `routes/formulas.py:138-160`
- §2.9 — insert — ambiguity — the `REDACTED` projection was wholly unspecified: nulls `raw_material_id`/`sub_formula_id`/`weight_pct`/`contribution_cents`, adds `weight_bucket` with labels `0-1`,`1-5`,`5-10`,`10-25`,`25-50`,`50-100` (upper bound inclusive), keeps `formula_id`/`component_type`/`sequence_no`/common props; the unredacted view carries no `weight_bucket` key — `serializers.py:109-130`
- §2.11 rung 3 — insert — ambiguity — `disclose_full` is not parsed until tier and live-ness pass; path resolution of `formula_id` precedes the rung — `routes/formulas.py:118-131,137`
- §2.11 rung 4 — insert — ambiguity — four request-shape conventions: absent/empty body reads as `{}` and non-object JSON is rejected; undeclared keys ignored; **JSON `null` treated exactly as omitted**; enum/code/role comparison exact and case-sensitive, duplicate-free code arrays reject repeats and preserve supplied order (only derived formula `allergen_codes` re-sorted); timestamps accept any ISO 8601 with numeric offsets normalised to UTC — `validate.py:15-41,99-128`, `db.py:89-115`, `routes/formulas.py:179-184`
- §4 preamble — insert — ambiguity — trailing slash tolerated; unlisted path → 404 `ERR_NOT_FOUND`; wrong method → 405 `ERR_METHOD_NOT_ALLOWED`; server fault → 500 `ERR_INTERNAL`; all three use the §2.2 envelope but sit outside the §5 catalogue — `app.py:22,32-48`

Pass 1 noted `validate.query_bool` as dead code (the composition read has its own inline copy) and pinned only the reachable inline behavior.

### Pass 2 — brief intake, raw-material catalogue, formula/component/costing core (`routes/briefs.py`, `routes/materials.py`, `routes/formulas.py`, `services/graph.py`, `services/costing.py`)

455/107114 → 455/112442 (+5328 bytes, no line loss, no `cp`). Headings verified byte-identical to `PRD_FINALIZED.md` (5 `##`, 20 `###`, 134 table rows). **17 ambiguity-pins, 2 mismatch-revisions.**

- §2.9 — insert — ambiguity — `disclose_full=true` with no grant at all (e.g. a TIER_1 read) also reports `ERR_REDACTION_LEVEL_INSUFFICIENT`; composition lines are emitted in ascending `sequence_no` = creation order as a single array — `routes/formulas.py:158-170`
- §3.1 — insert — ambiguity — `clarification_note` mandatory, string, length-unbounded (empty string accepted) — `routes/briefs.py:123`
- §3.1 — insert — ambiguity — `decision` is exactly `ACCEPTED|REJECTED`; an omitted `decision_note` leaves the stored value as-is rather than nulling it — `routes/briefs.py:146-157`
- §3.2 — insert — ambiguity — `claim_status`/`verified_claim_types` recomputed per read (the `claim_status` filter matches the derived value); `verified_claim_types` ascending and duplicate-free — `services/graph.py:99-111`, `serializers.py:48-49`, `routes/materials.py:77-78`
- §3.2 — insert — ambiguity — `valid_until` may lie in the past (a certificate can be filed already expired); duplicate `claim_type`s per material permitted — `routes/materials.py:113`
- §3.2 — insert — ambiguity — verification does not mutate the material record (`version`/`updated_at` stay put); `REVOKED → VERIFIED` retains the prior `revocation_reason` — `routes/materials.py:163-171`
- §3.2 — insert — ambiguity — `revocation_reason` mandatory, string, length-unbounded — `routes/materials.py:178`
- §3.2 — insert — ambiguity — `cost_per_kg_cents` mandatory despite `PATCH` (≥1 cent); a no-change reprice still bumps `version` and runs the cascade — `routes/materials.py:94-99`
- §3.3 — insert — ambiguity — formula creation gates neither the parent's status nor the brief's status — `routes/formulas.py:75-85`
- §3.3 — insert — ambiguity — a `confidentiality_tier` override may sit below the brief's tier; no ordering constraint — `routes/formulas.py:71-85`
- §3.3 — insert — ambiguity — `sequence_no` derived on every read, never stored — `serializers.py:95-97`, `services/graph.py:18-23`
- §3.3 — insert — ambiguity — with two dangling body references, `raw_material_id` resolves before `sub_formula_id` — `routes/formulas.py:190-195`
- §3.3 — insert — ambiguity — component **addition** is only accepted from `DRAFT|COSTED|REWORK_REQUIRED`, else `ERR_FORMULA_STATE_INVALID` (PRD previously stated this only for deletion) — `routes/formulas.py:207-209`
- §3.3 — insert — ambiguity — a sub-formula line may reference a formula of any brief and any status; only acyclicity constrains it — `routes/formulas.py:195,219-223`
- §3.3 — insert — ambiguity — add/delete does not advance the formula's `version` unless the fallback transition fires — `routes/formulas.py:54-59,240,447`
- §3.4 — insert — ambiguity — the four costing preconditions are reported per §2.11: own state, then `ERR_SUB_FORMULA_NOT_COSTED`, then empty-formula, then weight-sum — `routes/formulas.py:249-267`
- §3.5 — insert — ambiguity — `decision` is exactly `APPROVED|REWORK_REQUIRED`; `decision_note` validated but never retained — `routes/formulas.py:319-322`
- §3.5 — **revise** — **mismatch** — approval re-runs the whole forecast valuation (`variant_applied` and `stage_probability` too), not just `technical_factor`/`weighted_annual_value_cents` — `routes/formulas.py:341-347`, `services/cascade.py:31-56`
- §3.5 — **revise** — **mismatch** — same for the rework decision, plus an already-`AT_RISK` forecast is not visited at all on that path — `routes/formulas.py:352-357`
- §3.5 — insert — ambiguity — revision `name` 1–120 chars, `expected_formula_version` integer ≥1 (rung-4 rejection precedes the version compare), `carry_components` boolean defaulting false — `routes/formulas.py:365-369`
- §3.5 — insert — ambiguity — successor inherits the predecessor's tier (no override accepted); the `iteration_no` count includes the predecessor; HTTP 201 returns the successor — `routes/formulas.py:381-402`
- §3.9 — insert — ambiguity — a `loss_reason` sent with `outcome=WON` is enum-validated then discarded (won briefs report `loss_reason` null) — `routes/briefs.py:169-195`

Pass 2 deliberately left unpinned, as unobservable: `costing.apply_bench_cost` reads a sub-formula's stored `bench_cost_per_kg_cents` rather than recursing — the existing "already resolved" wording is accurate and the `ERR_SUB_FORMULA_NOT_COSTED` precondition makes the difference unobservable.

### Pass 3 — compounding/QC/retention, application testing, shipment/packet, scale-up, commercialization, ledger and cascade (`routes/lots.py`, `routes/tests.py`, `routes/shipments.py`, `routes/batches.py`, `routes/commercial.py`, `services/ledger.py`, `services/cascade.py`)

455/112442 → 455/116995 (+4553 bytes; all edits in-paragraph, no new lines or sections, no `cp`). **15 ambiguity-pins, 5 mismatch-revisions.**

- §3.6 — insert — ambiguity — formula `APPROVED` is the only cross-entity gate on compounding; the brief's status is never examined — `routes/lots.py:42-46`
- §3.6 — insert — ambiguity — `qc_by_user_id` starts null — `routes/lots.py:57`
- §3.6 — insert — ambiguity — `qc_note` validated as any-length string but never retained (no such field on the lot) — `routes/lots.py:93-94`, `serializers.py:133`
- §3.6 — insert — ambiguity — neither release nor any downstream allocation examines the owning brief's status — `routes/lots.py:112-129,186`, `routes/tests.py:84`, `routes/shipments.py:35`
- §3.6 — insert — ambiguity — `storage_temp_c` accepts at most six decimal places — `routes/lots.py:142-143`
- §3.6 — insert — ambiguity — cabinet capacity is tested before interval well-formedness/minimum-period, per the §2.11 ladder — `routes/lots.py:190-202`
- §3.6 — insert — ambiguity — `withdrawal_reason` mandatory, any-length free string — `routes/lots.py:254`
- §3.7 — insert — ambiguity — test `dosage_pct` range (>0, ≤100) is rejected at the shape rung, not as a dosage mismatch — `routes/tests.py:77-78`
- §3.7 — **revise** — **mismatch** — a test pass re-runs the whole §3.9 valuation (variant + stage + technical); `technical_factor` is 1.00 only while the brief still holds an `APPROVED` formula, else 0.55; forecast `status` is not moved (`AT_RISK` stays `AT_RISK`) — `routes/tests.py:198-200`, `services/cascade.py:46-62`
- §3.8 — insert — ambiguity — `carrier` is any-length and never revised afterwards — `routes/shipments.py:30-32`
- §3.8 — **revise** — **mismatch** — packet assembly is also refused from `PACKET_ASSEMBLED` — `routes/shipments.py:97-100`
- §3.8 — insert — ambiguity — neither assembly nor dispatch re-examines the lot's disposition or the formula's status — `routes/shipments.py:92-158`
- §3.8 — insert — ambiguity — re-assembly re-stamps `generated_at` and advances `version` on retained documents, `PINNED` ones included — `services/cascade.py:298-300`
- §3.8 — insert — ambiguity — `tracking_reference` mandatory, any-length string — `routes/shipments.py:117`
- §3.8 — **revise** — **mismatch** — `LOT_HELD` is the only `block_reason` ever written; `SUBSTANTIATION_REVOKED` is declared but unproduced — `services/cascade.py:83`
- §3.8 — insert — ambiguity — `cancellation_reason` mandatory free string, not an enum member — `routes/shipments.py:165`
- §3.9 — insert — ambiguity — no brief-status gate on scale-up; a new batch displaces no earlier batch — `routes/batches.py:22-52`
- §3.9 — insert — ambiguity — a rejection's `decision_note` survives re-specification — `routes/batches.py:92-97`
- §3.9 — insert — ambiguity — `measured_yield_kg` ≥ 0 with ≤4 decimals; `decision` enum; omitted `decision_note` leaves the prior value — `routes/batches.py:105-106,124-135`
- §3.9 — **revise** — **mismatch** — `BATCH_SUPERSEDED` is a declared enum member no operation writes (only `FORMULA_REWORK`/`PARENT_SUPERSEDED` cascades cancel) — `services/cascade.py:101-110`, `routes/formulas.py:399`
- §3.9 — insert — ambiguity — `expected_brief_version` must be an integer ≥1 (`ERR_INVALID_REQUEST` before the version comparison); supersession touches only `ACTIVE`/`AT_RISK`; publication has no brief-status precondition — `routes/commercial.py:29-39`
- §3.9 — **revise** — ambiguity — the risk-weighted variant covers every status except `CLOSED_WON`; `stage_probability` 0.10 also for `DRAFT`, `REJECTED`, `CLOSED_LOST` — `services/cascade.py:34-56`

Pass 3 verified two behaviors as already correctly pinned and left them untouched (the `formula_left_approved` four-consequence cascade including the `cost_stale` reset, §3.5; and the disclosure-grant expiry boundary, §2.9). Two impl branches were deliberately not documented because no API path can reach them: `assemble_packet`'s empty-leaf-materials `ERR_DOC_PACKET_INCOMPLETE`, and re-pinning skipping a document whose type has dropped out of the requirement set (no endpoint mutates a brief's claim flags, a shipment's destination, or a formula's tier).

### Totals and orchestrator verification

**45 edits: 45 pins/revisions across the three passes (28 → 30 → …; ambiguity-pins 13+17+15 = 45, mismatch-revisions 0+2+5 = 7).**

Independently re-verified after pass 3: `PRD.md` 451/97122 → `PRD_FINALIZED.md` 451/98070 → `PRD_COMPLETED.md` 455/116995 (+19.9% bytes over `PRD_FINALIZED.md`). `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (`cmp` differs), so the scan genuinely ran. Structure intact: 5 `##` sections, 20 `###` subsections, exactly 61 `ERR_*` rows in §5, and the file still ends at a real section boundary (`| ` + `ERR_COST_IN_USE_CAP_EXCEEDED` + ` | 422 |`) with no mid-sentence truncation.

`__pycache__` trees removed from `test_helpers/`, `test_suite/` and `workspace/implementation/**` after the final pass. Final state: 123/123 tests green in all 8 sweep rounds, `workspace/implementation/results.{1..8}.json` retained as evidence.

**Pipeline complete.**
