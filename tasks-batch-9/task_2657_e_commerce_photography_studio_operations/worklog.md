## Step 1: Create task directory — 2026-09-04T02:04:30.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2657_e_commerce_photography_studio_operations and its workspace/ subdirectory. Index 2657 was pre-assigned by the invoking pipeline (no ./tasks/ scan performed, per orchestration instructions — up to 32 pipelines run concurrently on this host and auto-allocation would collide).

## Step 2: Generate scaffold — 2026-09-04T03:18:00.000Z

Scaffold generation for task 2657 is complete and lint-clean.

**Files**
- `/home/ubuntu/github/CodingPRD/tasks/task_2657_e_commerce_photography_studio_operations/SCAFFOLD.yaml` — 2797 lines (146 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_2657_e_commerce_photography_studio_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2195 lines (138 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_2657_e_commerce_photography_studio_operations/SCAFFOLD_CORNER_DESIGN.yaml` — 3703 lines (226 KB)

**SCAFFOLD.yaml (§1.0–§1.7)** — `domain_name: ecommerce-photo-studio-ops`, `api_prefix: /studio`; profile: temporal_windowing + workflow_orchestration, graph topology, parallel state machines, segregation_of_duties roles, immediate consistency.
- 13 entities, 9 state machines (Sample carries two parallel axes: custody + match), 2 §1.2.1 concurrency rules, 9 calculations (2 dual-variant), 50 priority-ordered validations, **56 endpoints**, 53 errors, 7 roles (StudioAdmin, SampleCoordinator, Producer, Photographer, Retoucher, QCReviewer, ContentOps).
- Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — single top-level key; all **9 difficulty rules** present, **24 instances** total (2–3 per rule), each with the 7-point contract and precomputed literal asserts.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — single top-level key; all **9 taxonomy sections** (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross-cutting complexity layers, consistency model) with **80 instances**: 60 full `test_recipe` instances plus 20 `excluded_because` stubs, every stub citing an existing §1.8 instance by exact name (0 dangling citations).

**Verification**
- `scaffold_lint.py`: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (56 endpoints, 13 entities, 24 §1.8 instances, 60 §1.9 recipes, **1083 calls scanned**).
- All **53/53 error codes** are triggered somewhere across §1.8 + §1.9.
- All three files parse as YAML; built via chunked appends, no single oversized write.
- Two incidental fixes to SCAFFOLD.yaml prose cross-references (`validations[priority=42]` → 47 for the release selector, `priority=38` → 43 for the station-type gate); one field-name correction in the last corner instance (`committed_minutes_today` / `booked_minutes_today`, not `booked_minutes_by_date`).
- No sibling task directory was read, listed, or grepped at any point.

Orchestrator verification: all three files present; top-level keys confirmed (SCAFFOLD.yaml has neither design key; the two design files each carry exactly their single design key).

## Step 3: Copy shared files — 2026-09-04T03:18:30.000Z

Copied ./INSTRUCTION.md to tasks/task_2657_e_commerce_photography_studio_operations/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T03:35:00.000Z

All three contracts verified mechanically after the final §2.6 strengthening edit. PRD.md is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2657_e_commerce_photography_studio_operations/workspace/PRD.md` — **424 lines**, built with 11 chunked `cat >> ... <<'PRDEOF'` appends (no single giant Write; no truncation).

**Tail confirmation** — ends at a completed section boundary: the last 40 lines are the closing rows of the §5 two-column error table, final line `| `ERR_NO_CLAIMABLE_TASK` | 409 |`. No mid-sentence cut, no partial table row.

**Top-level sections emitted**
- `# Ecommerce Photo Studio Ops API — Product Requirements Document`
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Users, Roles and Studio Access Control / 2.2 API Response Structure (verbatim contract, `cat`-copied byte-for-byte) / 2.3 Pagination / 2.4 The Logical Studio Clock / 2.5 Resource Identity, Versioning and the Immutable Content Profile / 2.6 Optimistic Concurrency on Parent Records / 2.7 The Order in Which a Request Is Judged (8-tier normative ladder naming all 53 error IDs in priority order) / 2.8 Minutes, Cents, Hours and Rounding / 2.9 Ledgers, Counters and Cascades / 2.10 Flat Addressing and Filtered Discovery
- `## 3. Business Logic & Workflows` — 3.1 Standing Up the Studio / 3.2 Styles, Colorways and the Compound Content State / 3.3 Sample Custody / 3.4 Booking the Floor / 3.5 Crewing the Session / 3.6 Defining and Assigning the Shot List / 3.7 Shoot Day / 3.8 Post-Production / 3.9 Delivery into the CMS and the Cost-per-Style Comparison
- `## 4. Endpoint Definitions` (4-column table: Method, Path, Description, Authorized Role(s) — all 56 rows)
- `## 5. Error Code Catalogue` (2-column table: Error ID, HTTP Status Code — all 53 rows)

Field coverage check: entities[].fields 126/126; endpoints[].request_body 79/79; query_params 34/34; path_params 13/13. Status: PASS
Rule coverage check: 50/50 validations; 2/2 OCC rejections; 59/59 transitions; 9/9 calculations; 50/50 error-id-matchable conditions; 34/34 side_effects; 126/126 field structures; 14/14 sibling-branch symmetry groups. Status: PASS
Path purity check (§3 only): 889 backtick tokens scanned, 0 path tokens, 0 bare HTTP-method tokens, 0 method+path tokens. Status: PASS

**Coverage confirmed in prose:** 13 entities, 56 endpoints, 9 state machines / 59 transitions (35 as explicit `A → B` tokens, 24 in sentence form), 9 calculations, 50 validations, 53 errors, 7 roles. The 11 error IDs appearing only outside §3 (`ERR_UNAUTHENTICATED`, `ERR_FORBIDDEN_ROLE`, `ERR_INVALID_REQUEST`, the five `*_NOT_FOUND` codes, `ERR_STALE_SESSION_VERSION`, `ERR_STALE_STYLE_VERSION`) are envelope-level checks belonging to the §2 precise zone by design.

**Scaffold conflicts resolved during authoring** (all decided in favour of the normative rule statements, applied consistently across §2.7 and §3):
- `StudioProvider.capacity_assets_per_day` field prose says "at or above this count are excluded", but the `QUEUED → IN_PROGRESS` precondition and the `retouch_priority_score` selector both say `assigned_asset_count <= capacity_assets_per_day` — wrote `<=` ("no greater than").
- `Sample RECEIVED → LOST` lists only the L1 vendor-ledger effect while the three sibling `→ LOST` transitions list L1..L4, yet the endpoint `side_effects` list L1..L4 unconditionally — wrote the unified guarded cascade matching the Style machine's own preconditions.
- Asset-ingest error list orders `ERR_SHOT_ITEM_NOT_ASSIGNABLE` before `ERR_SESSION_NOT_SHOOTING`, contradicting the global priority ladder (15 before 18) — the ladder is normative.
- Priority 46 (`ERR_SAMPLE_NOT_IN_STUDIO`) precedes 52 (`ERR_SHOT_LIST_EMPTY`); §3.7 explains the sample check ranges only over required assigned items, so an empty list passes it vacuously and `ERR_SHOT_LIST_EMPTY` still surfaces.

Both withheld design files were never opened, grepped, or referenced, and no sibling task directory was read.

Orchestrator truncation check (per the known doc-generator failure mode): PRD.md is 424 lines; §5 error table has exactly 53 `ERR_*` rows and §4 endpoint table exactly 56 method rows; the file ends on the final complete table row. NOT truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T04:04:00.000Z

The implementation is complete and verified.

## Files written — `workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `app.py` | 66 | Flask app factory, 7 blueprints at `url_prefix="/studio"`, `ApiError`/404/405/HTTPException/Exception handlers, `app.run(host="0.0.0.0", port=int(os.environ["PORT"] or 10000))` |
| `core.py` | 619 | Constants, enums, 53-code `ERROR_STATUS`/`DEFAULT_MESSAGES`, `ApiError`/`fail`, Decimal+ROUND_HALF_UP helpers, ISO-8601 parse/emit, in-memory `Store` + logical clock, response envelope, RBAC `authorize`, body/query validators, pagination |
| `logic.py` | 372 | Ledger recounts, booking charge, allocation waterfall, `cost_summary`, pinned SLA, turnaround, priority score, `claim_candidates`, colour composite/baseline, return lateness, vendor strikes |
| `cascade.py` | 202 | Sample→LOST depth-4 block cascade, session cancel/wrap, asset ingest/reject/deliver depth-4 delivery cascade |
| `serialize.py` | 245 | 13 per-entity serialisers; every denormalised counter rendered from a recount |
| `routes_config.py` | 426 | Clock, vendors, asset profiles, stations, talent profiles, providers, styles, cost-summary, release documents |
| `routes_samples.py` | 220 | Create/receive/match/custody-move/return/report-lost + reads |
| `routes_sessions.py` | 252 | Create/lock/unlock/cancel/start/color-measurement/wrap + reads, `photographer_gate` |
| `routes_bookings.py` | 180 | Create (OCC)/confirm/cancel + reads, release-document selector |
| `routes_shotlist.py` | 142 | Create (OCC)/assign/waive + reads |
| `routes_assets.py` | 140 | Ingest (calibration→colour→dup→naming→metadata order), deliver + reads |
| `routes_retouch.py` | 206 | Create, claim-next selector, submit, qc-decision (SoD, rework recycling, abandon) + reads |
| `start.sh` | 10 | `exec python3 app.py`, `$PORT`, foreground, flask installed only when missing |
| `requirements.txt` | 1 | `flask==3.0.3` |

Total 2,870 lines of Python. Storage is in-memory dicts only; nothing is seeded at import or boot.

## Verification
- `python3 -m py_compile` on all 12 `.py` files: **OK**; `import app` also succeeds.
- **Endpoint parity**: url_map vs SCAFFOLD.yaml — 56 declared, 56 implemented, **0 missing, 0 extra**.
- **RBAC parity**: role sets for all 56 endpoints compared against the scaffold — **0 mismatches**.
- **Input-name parity**: every `input:` field name across all 34 POSTs matches the scaffold.
- `start.sh` correctness for `--isolation per-test-server` confirmed empirically: the launched shell PID becomes `python3 app.py` via `exec` (single PID, no orphan child), so the harness's kill releases the port.

## Smoke test (`PORT=18657 bash start.sh`, killed by captured listener PID; never a pattern kill)
Boot in <2s. Full happy path exercised end to end — all statuses as expected: clock/vendors/asset-profiles/stations/talent-profiles/providers/styles 200-201; samples receive→match→custody-move (style SAMPLE_READY); shoot-session→talent-booking (charge 40000 = 4h × 10000)→confirm→shot-list-item→assign→lock→start→color-measurement (composite 0.88, PASS); asset ingest (`TS10442_FRONT_007`) → item CAPTURED, style SHOT → wrap → allocation `final_cost_cents` 40000; retouch tier-A rush (`sla_hours` 24→12) → claim-next (style IN_POST) → submit → qc-decision 403 `ERR_SEGREGATION_OF_DUTIES` → REJECT (REWORK, rework_count 1) → resubmit → APPROVE (`turnaround_hours_gross` 12.0, `sla_state` AT_RISK, `priority_score` 109.0); deliver → `cms_asset_key` `APPAREL_TOP/TS10442/TS10442_FRONT_007`, style DELIVERED, sample RETURN_PENDING (depth-4 delivery cascade). Negative checks: 401 `ERR_UNAUTHENTICATED`, 404 unknown id, 409 `ERR_DUPLICATE_CODE` ×4, 400 `ERR_INVALID_REQUEST`, 403 `ERR_FORBIDDEN_ROLE`.

Server killed by PID; port 18657 free; `__pycache__` removed. No pattern kill was ever issued.

## Step 5: Generate unit tests — 2026-09-04T04:44:00.000Z

Both remaining files are written and the suite is complete.

## Files written

`test_helpers/` (Stage 1, 9 files, 2,148 lines): `__init__.py` 45, `api_client.py` 379, `api_errors.py` 135, `assertions.py` 168, `constants.py` 102, `factories.py` 378, `fixtures.py` 613, `test_users.py` 77, `types.py` 251.

`test_suite/` (Stage 2, 19 files, 5,523 lines): `conftest.py` 36; queue A `test_01` 173, `test_02` 374, `test_03` 164, `test_04` 155, `test_05` 221, `test_06` 296, `test_07` 309, `test_08` 264, `test_09` 224; queue B `test_10` 365, `test_11` 344, `test_12` 337, `test_13` 200, `test_14` 246, `test_15` 836, `test_16` 371, `test_17_corner_complexity_layers.py` 439, `test_18_corner_consistency.py` 169.

Both directories are at the task root; nothing was created or read under `workspace/implementation/`, and no sibling task directory was touched.

## Tests emitted

- **Queue A (Difficulty):** 65 tests across 9 rule_ids covering **24 of 24** instances.
- **Queue B (Corner):** 112 tests covering **60 of 60** non-stub instances (entities 12, state_machines 8, calculations 6, validations 5, endpoints 5, errors 12, rbac 6, cross-cutting complexity layers 4, consistency model 2). The 20 `excluded_because:` stubs are correctly untranslated.
- **Total: 177 tests, 177 `Design:` tags** — exactly one per test, every tag resolving to a real `rule_id`/`section` + instance name (verified programmatically), 84 distinct instances referenced.

## Instances skipped

**Zero.** No instance failed the PRD-first filter outright. Two design defects were handled inside the affected instances rather than by skipping:

1. `consistency model / cascade_effects_are_visible_on_the_first_read_after_the_write` asserts `charge_cents == 0` on a cancelled booking; PRD §3.5 says the charge is "computed at hold time, frozen onto the row, and never recomputed afterwards — not at confirmation, not at wrap, not at cancellation." That single assertion is **omitted**; the rest of the cascade (item `PLANNED` + `session_id` null, booking `CANCELLED`, station `committed_minutes_today` 0, talent `booked_minutes_today` 0) is asserted.
2. The same instance's recipe assigns a `STILL_ANGLE` item to a `MODEL` station, which PRD §3.6 refuses with `ERR_STATION_TYPE_MISMATCH`. The setup was minimally corrected to an `ON_MODEL` item so the fixture is legal; the instance's immediacy claim is unchanged.

## Verification

- `python3 -m py_compile` on all 9 helper files and all 19 suite files: **ALL OK**.
- `python3 -m pyflakes` over both directories: **clean, exit 0**.
- Verbatim citation check (every `PRD: "…"` line grepped as a literal substring of `workspace/PRD.md`): **177 tests / 177 tags / 0 misses**.
- `pytest --collect-only`: **177 tests collected, no collection errors**.

Orchestrator note: Steps 5 and 6 were launched back-to-back as background agents. Step 6's impl generator was spawned within seconds of Step 5 and was explicitly forbidden from reading `test_helpers/`/`test_suite/`; Step 5 was likewise forbidden from reading `workspace/implementation/`. Its own report confirms it never read that directory. Verified after both exited that `test_helpers/` and `test_suite/` live at the task root with no strays under `workspace/`.

## Step 7: Run tests and iterate — 2026-09-04T05:05:00.000Z

All 8 parallel rounds are green: `total=177, passed=177, failed=0, errors=0, skipped=0` in every one of `results.1.json` … `results.8.json`.

## Summary

**Iterations run:** 2 (iteration 1: 16/177 failing, deterministic across all 8 rounds; iteration 2: 177/177 in all 8 rounds).

**Tests deleted:** none. No failing test turned out to rest on PRD silence — every one traced to a verbatim PRD sentence, so all 16 were resolved at STEP 2 as test bugs.

**Fixes applied to `test_helpers/`**

| File | Fixture / factory | Why |
|---|---|---|
| `test_helpers/factories.py` | new `_talent_of_type()` backing `photographer_payload` / `retoucher_payload` / `model_payload` / `stylist_payload` | They passed per-type defaults as keywords to `talent_payload()` *and* splatted `**overrides`, so any caller naming `full_name`, `hourly_rate_cents`, … raised `TypeError: got multiple values for keyword argument`; now merged with `setdefault` so caller overrides win. Root cause of 13 of the 16 failures (test_02 ×3, test_06 ×3, test_16 ×5, test_17 ×2). |
| same file | `outsourced_provider_payload()` | Same latent collision (it splatted its own 8 defaults into `provider_payload`); rewritten to the same `setdefault` shape pre-emptively. |

**Fixes applied to `test_suite/`**

| File | Test | Why |
|---|---|---|
| `test_10_corner_entities.py` | `test_the_junction_and_colorway_edges_are_reachable_by_filtered_lists` | Setup created a colourway with `style_number="TOP1001-BLK"`; PRD §3.2 says a style number is "4 to 16 uppercase alphanumeric characters", so the hyphen is illegal and the setup died on `ERR_INVALID_REQUEST`. Changed to `TOP1001BLK` (the same file's sibling tests already use `TOP1001NVY`/`TOP1001RED`). |
| `test_15_corner_errors.py` | `test_a_reading_a_whole_unit_off_the_stations_last_pass_is_rejected` | Asserted `color_patch_deltas is None` after a drift refusal, but PRD §3.4 says the field is born as "an empty array" (only the composite, verdict and timestamps are null), and the refusal persists "nothing at all" — so it is still `[]`. Assertion corrected to `== []`. |
| `test_15_corner_errors.py` | `test_a_second_task_over_the_same_asset_is_refused` | Asserted `ERR_RETOUCH_TASK_EXISTS`, but the queued first task has already moved the file `INGESTED → IN_RETOUCH` (PRD §3.8), and both the cited sentence and the §2.7 ladder run the `INGESTED` requirement (`ERR_ASSET_NOT_APPROVED`, state-precondition tier 6) *before* the live-task rule (tier 8). Assertion corrected to `ERR_ASSET_NOT_APPROVED` / 409 — still an exact `error_id`, not an HTTP-status downgrade, with the precedence reasoning recorded in the docstring. |

**Fixes applied to `implementation/`:** none. No implementation change was needed or made; `workspace/implementation/` is byte-identical to what Step 6 produced.

Both new test-layer decisions were checked against the reachability question: with a live task the asset can never be `INGESTED` under the PRD's own asset machine, so `ERR_RETOUCH_TASK_EXISTS` is not isolable by any PRD-legal fixture — the PRD-determined refusal for this precondition is the one now asserted. `py_compile` and `pyflakes` are clean over both directories.

Orchestrator verification (per the known failure mode where a Step 7 agent reports a clean sweep with no artifacts on disk): independently re-read all 8 `workspace/implementation/results.$i.json` files — every one reports total=177, passed=177, failed=0, errors=0, skipped=0, all timestamped 05:00. Sweep artifacts confirmed present and green.

Step 8 skip-condition adjudication: NOT skipped. Step 7 ran 2 iterations with 3 `test_suite/` fixes and 2 `test_helpers/` fixes. Although `implementation/` was never edited, two of the `test_suite/` fixes (the `color_patch_deltas == []` correction and the `ERR_ASSET_NOT_APPROVED` precedence correction) are precisely the signal Step 8 exists to consume — they mark PRD passages whose wording did not, on its own, pin the behaviour the implementation had already chosen. Step 8 runs with those items as its focus list.

## Step 8: Finalize PRD — 2026-09-04T05:12:00.000Z

`PRD_FINALIZED.md` is written. Step 7's diff contained **no `implementation/` fixes and no test deletions** — every one of the 16 iteration-1 failures was resolved as a test-side bug against a verbatim PRD sentence — so the patch surface was genuinely tiny. Each of the five diff items was verified against the impl; exactly one place was found where the impl pins a choice the PRD leaves open.

## Line counts
- `PRD.md`: 424 lines; `PRD_FINALIZED.md`: 424 lines → **0.0% line delta** (1 line revised in place, no lines added/removed).

## Changes
- **§2.7 item 2 (Request shape)** — *revise* — added that string-typed fields must respect their **declared length bounds and character set**, and that a violation (e.g. a hyphen in a field declared uppercase alphanumeric) is rejected at the request-shape tier as `ERR_INVALID_REQUEST` rather than stored or judged by a later rule — `implementation/core.py:447-463` (`vstr` min/max/pattern → `ERR_INVALID_REQUEST`), enforced at `implementation/routes_config.py:262` (`style_number`, `pattern=^[A-Z0-9]+$`, 4–16).

### Pre-edit search log (edit 1)
- **(a) Subject:** which tier and which `error_id` a declared string length/character-set violation produces (surfaced by the `test_10` fix, where `style_number="TOP1001-BLK"` died on `ERR_INVALID_REQUEST` during setup; PRD §3.2 declares the charset but §2.7 tier 2 enumerated only types, enums, non-empty arrays and numeric ranges).
- **(b) Paths enumerated:** grepped every `vstr(` callsite in the impl (37 sites across `routes_config.py`, `routes_samples.py`, `routes_sessions.py`, `routes_bookings.py`, `routes_shotlist.py`, `routes_assets.py`, `routes_retouch.py`) and read `core.vstr` / `_present` / `venum` / `varray` / `vobject`. Confirmed **every** length/pattern violation raises `ERR_INVALID_REQUEST`, and that validation always precedes path/FK resolution (`find`) in each handler, i.e. tier 2. Also checked the neighbouring paths that could be mis-swept: `file_name` (shape = length only; pattern equality is the tier-8 `ERR_ASSET_NAMING_VIOLATION` at `routes_assets.py:58`), `metadata_tags` values (`ERR_ASSET_METADATA_INCOMPLETE`, `routes_assets.py:65-69`), `declared_style_number` vs style (`ERR_STYLE_NUMBER_MISMATCH`, `routes_samples.py:113`), `naming_pattern` token check (`ERR_INVALID_REQUEST`, `routes_config.py:90`), `station_code`/`barcode` (hyphens **are** legal, `UPPER_NUM_DASH`).
- **(c) Wording adjustment:** scoped the clause to *declared* length/charset constraints and phrased the example as "a character its declaration does not allow", so it does not (i) claim anything about the impl's undeclared caps (`contact_email` 320, `agency_name`/`session_label` 200, notes/reasons 1000/2000), (ii) sweep in `file_name`/`metadata_tags`, whose violations keep their own tier-8 codes, or (iii) forbid hyphens in `station_code`/`barcode`, where the declaration allows them. Also left whitespace-trim ordering unstated (impl strips `style_number` before measuring) to avoid a false universal.

## Items deliberately left unpatched (PRD already determines them)
- `test_helpers/factories.py` `_talent_of_type()` and `outsourced_provider_payload()` — pure Python keyword-collision bugs (`TypeError`); the merged defaults are test-side data with no impl-behaviour content. No PRD silence.
- `test_15` `color_patch_deltas == []` after a drift refusal — PRD §3.4 already says the field is born "an empty array" (only composite/verdict/timestamps null) and §3.7 already says a drift refusal persists "nothing at all"; impl matches exactly (`routes_sessions.py:105,194-199`, serialized as `[]` at `serialize.py:164`). Prose kept verbatim.
- `test_15` `ERR_ASSET_NOT_APPROVED` before `ERR_RETOUCH_TASK_EXISTS` — PRD §3.8 sentence order and the §2.7 ladder (asset-state legality at tier 6, live-task rule at tier 8) already fix the order; impl checks `asset_state != "INGESTED"` first (`routes_retouch.py:30-36`). Prose kept verbatim.

Orchestrator verification: `PRD_FINALIZED.md` exists, is 424 lines, and is NOT byte-identical to `PRD.md` — `diff` shows exactly one revised line (line 111, §2.7 tier 2). The patch really was applied.

## Step 9: Complete PRD — 2026-09-04T05:35:00.000Z

Orchestrator decision (reasoning recorded here per the autonomy instruction): Step 9 was run as **three sequential file-partitioned passes** over `implementation/` rather than one monolithic subagent, because a single agent asked to walk 3,070 lines of implementation against a 424-line PRD reliably runs out of working room and returns a `PRD_COMPLETED.md` that is byte-identical to its source — i.e. the scan never actually ran. Each pass edited the same `PRD_COMPLETED.md` in place with targeted Edit calls, and each was told which modules earlier passes had already covered and which findings not to redo.

### Pass 1 — app.py, core.py, logic.py, serialize.py (1,302 lines)
`PRD_COMPLETED.md` created by `cp` from `PRD_FINALIZED.md`, then **13 edits** (13 ambiguity-pins, 0 mismatch-revisions). Chars 93,701 → 98,550 (+4,849); lines unchanged at 424.
- §2.1 — insert — ambiguity — whitespace-only header value counts as empty (401); both header values trimmed before use — `core.py:398-412`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars, minted for error responses too — `core.py:352-354,385-391`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the host wall clock, not the logical studio clock — `core.py:357-363`
- §2.3 — insert — ambiguity — boolean filters accept `true/false/1/0` case-insensitively; `scheduled_date` must be `YYYY-MM-DD`; identifier filters are opaque strings never checked for existence (empty page, not 404) — `core.py:579-613`
- §2.3 — insert — ambiguity — `created_at` ties ordered by creation sequence; `id` never participates — `core.py:345-346,617-619`
- §2.4 — insert — ambiguity — clock may be set backwards; echo rendered with 3 fractional digits — `core.py:279-283`, `routes_config.py:29-36`
- §2.4 — insert — ambiguity — lazy `EXPIRED` transition is a real mutation (version++/`updated_at`) even when it fires during a read — `logic.py:102-106`, `serialize.py:133`
- §2.5 — insert — ambiguity — client instants: optional seconds/fraction, `T`-or-space separator, `Z`/`±HH:MM`/`±HHMM` normalised, no-zone read as UTC, unparseable → `ERR_INVALID_REQUEST` — `core.py:240-267,515-522`
- §2.7 step 2 — insert — ambiguity — explicit `null` == omission; undeclared fields ignored; absent/empty body read as `{}`; strict types (bool never an int, int refuses fractional, numeric string is not a number) — `core.py:425-552`
- §2.8 — insert — ambiguity — instant-derived minute counts floor the part-minute remainder — `core.py:226-227`
- §2.8 — insert — ambiguity — two decimals is a *rendering* rule; finer client precision stored/compared at full precision — `core.py:230-234`, `serialize.py:87,163`
- §2.10 — insert — ambiguity — trailing slash accepted as equivalent — `app.py:24`
- §3.8 — insert/revise — ambiguity — `priority_score` computed at read time against the current clock without bumping version; residual claim-ranking `created_at` tie resolved by creation order — `serialize.py:231`, `logic.py:301-327`
- §4/§5 preambles — insert — ambiguity — `reason`/`note`/`cms_collection` validated but never persisted; unknown path → `ERR_REFERENCE_NOT_FOUND` 404, undeclared method → `ERR_INVALID_REQUEST` **405** — `app.py:37-45`, `serialize.py:114-129,209-245`

### Pass 2 — routes_config.py, routes_samples.py, routes_sessions.py (898 lines)
**15 edits** (12 ambiguity-pins, 3 mismatch-revisions). Chars 98,550 → 101,096 (+2,546). All 13 pass-1 pins verified intact.
- §2.7 step 2 — revise — mismatch — pass 1's universal claim that a non-object body is rejected was false for the seven action endpoints that never call `get_body()`; carved them out — `routes_samples.py:69`, `routes_sessions.py:116,143,166,212`, `routes_bookings.py:96`, `routes_retouch.py:70`
- §3.1 — insert ×5 — ambiguity — vendor `name` 1–120 measured raw and stored verbatim; `contact_email` max 320 with no syntax check; no `required_metadata_keys` member may be blank; talent `full_name` has no non-whitespace test and `agency_name` maxes at 200; non-zero `style_quote_cents` on `IN_HOUSE` is `ERR_INVALID_REQUEST` ahead of code uniqueness — `routes_config.py:46-52,118-125,180-182,227-232`
- §3.2 — insert ×2 — ambiguity — `style_number` stripped before length/charset/uniqueness and the trimmed value stored; body FK order `vendor_id` → `asset_profile_id` → `base_style_id` — `routes_config.py:262-278`
- §3.3 — insert ×3 — ambiguity — pre-advice seeds `return_days_late` 0 and nulls `received_at`/`due_return_at`/`returned_at`/`condition_note`; matching is repeatable from any match state while custody is non-terminal and a `HOLD` knocks `MATCHED` back to `MISMATCH_HOLD`, touching only the sample row; `to_state` is declared over all seven custody states so `EXPECTED`/`RETURNED`/`LOST` fail 409, not 400 — `routes_samples.py:51-63,101-130`
- §3.4 — insert ×2, revise ×1 — `session_label` max 200/default null and `color_chart_code` 1–64 (ambiguity); a `SHOOTING` session also refuses cancellation with `ERR_SESSION_TERMINAL` (mismatch) — `routes_sessions.py:46-48,159-160`
- §3.5 — revise — mismatch — a new release does not always land `PENDING`: creation runs `release_out` → `refresh_release`, so a back-dated `valid_until` returns `EXPIRED` at version 2 — `routes_config.py:375-385`, `serialize.py:133`
- §3.7 — insert — ambiguity — patch readings must be numbers but carry no declared bounds — `routes_sessions.py:182`

### Pass 3 — routes_bookings.py, routes_shotlist.py, routes_assets.py, routes_retouch.py, cascade.py (870 lines)
**17 edits** (16 ambiguity-pins, 1 mismatch-revision). Chars 101,096 → 105,121 (+4,025).
- §2.6 — insert — ambiguity — `expected_*_version` are integers ≥ 0, so a negative value is `ERR_INVALID_REQUEST` at step 2, not a staleness failure — `routes_bookings.py:45`, `routes_shotlist.py:32`
- §2.7 step 4 — insert — ambiguity — two-body-FK order: `session_id` before `talent_id`; `asset_id` before `provider_id` — `routes_bookings.py:47-48`, `routes_retouch.py:27-28`
- §2.9 — revise — mismatch — the universal "a parent's version increments once per cascade, not once per touched child" was false for a talent in the session-cancel cascade; qualified — `cascade.py:113`
- §3.2 — insert — ambiguity — SHOT/DELIVERED completion tests are judged over a non-empty set; a style with no required non-waived item satisfies neither vacuously — `cascade.py:19-38`
- §3.4 — insert ×2 — ambiguity — the station row is never rewritten by a session's lifecycle (`committed_minutes_today` is a pure recount); a talent's version increments once per reversed booking — `cascade.py:101-120`
- §3.5 — insert ×2 — ambiguity — the covering-release search first applies lazy expiry to every release and only runs for a `requires_release` talent; `created_at` ties broken by insertion order and `territory` plays no part — `routes_bookings.py:19-33,107`
- §3.6 — insert ×4 — ambiguity — session state judged before item state on assign; every ingest and rejection rewrites the item row; blocking leaves `session_id` intact; a non-required waive does not rewrite the style and waiving never re-evaluates `content_state` — `routes_shotlist.py:70-73,101-108`, `cascade.py:76-81,151,172`
- §3.7 — insert ×3 — ambiguity — `file_name` 1–300; `metadata_tags` a required object stored verbatim including extra keys; a null-`session_id` item is refused `ERR_NOT_BOOKED_ON_SESSION` ahead of every state check; a still-`HELD` booking stays `HELD` at wrap and no talent row is rewritten — `routes_assets.py:28-36,76`, `cascade.py:126-139`
- §3.8 — insert ×2 — ambiguity — rework leaves `assigned_retoucher_id`/`claimed_at`/`submitted_at` standing; abandon measures no turnaround (both variants and `approved_at` stay null, `sla_state` stays `IN_SLA`) — `routes_retouch.py:153-173`
- §3.9 — insert — ambiguity — each retargeted sample's version increments; no vendor row is rewritten because `RETURN_PENDING` is still outstanding — `cascade.py:197-202`

### Totals and completion check
- **45 edits across the three passes: 41 ambiguity-pins, 4 mismatch-revisions.**
- `PRD.md` 424 lines / 93,279 chars → `PRD_FINALIZED.md` 424 / 93,701 → `PRD_COMPLETED.md` 424 / 105,121 (**+11,420 chars over PRD.md, +12.2%**; every change in-paragraph, no new sections).
- Orchestrator-verified independently: `cmp PRD_FINALIZED.md PRD_COMPLETED.md` differs; `diff` shows **41 revised lines** (so the scan demonstrably ran and was not a byte-identical no-op); §4 still has 56 endpoint rows and §5 still has 53 `ERR_*` rows; the file ends at a real section boundary on the final error row.
- Also verified no `.py` file under `workspace/implementation/`, `test_suite/` or `test_helpers/` is newer than the green sweep artifacts — Steps 8 and 9 touched documentation only, so the 8/8 green result from Step 7 still describes the shipped code.

Pipeline complete through Step 9.
