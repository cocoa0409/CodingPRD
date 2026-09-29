# Worklog — task_2612_guitar_factory_operations

## Step 1: Create task directory — 2026-09-03T19:42:20.243Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2612_guitar_factory_operations` and `.../workspace` (pre-assigned path from the orchestration prompt; no index auto-allocation performed, per instruction — 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T21:35:33.642Z

Task 2612 scaffold is complete and lints clean.

## Output directory
`/home/ubuntu/github/CodingPRD/tasks/task_2612_guitar_factory_operations/`

```
SCAFFOLD.yaml                     3769 lines  (§1.0–§1.7; no design keys)
SCAFFOLD_DIFFICULTY_DESIGN.yaml    770 lines  (single key scaffold_difficulty_design, §1.8)
SCAFFOLD_CORNER_DESIGN.yaml       1926 lines  (single key scaffold_corner_design, §1.9)
worklog.md + workspace/           untouched
```

## Lint verdict
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
  §1.5 endpoints declared:    84
  §1.1 entities declared:     15
  §1.8 instances scanned:     29
  §1.9 instances scanned:     70
  Calls scanned (§1.8+§1.9):  1309

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## §1.9 breadth (97 instances, 70 with recipes + 27 `excluded_because` stubs)
entities 13 · state_machines 13 · calculations 12 · validations 17 · endpoints 8 · errors 20 · rbac 6 · cross_cutting_complexity_layers 7 · consistency_model 1. Every claim-type row of `claim-extraction-guide.md` applicable to this scaffold is instantiated (only `bulk_action` is skipped — §1.5 declares no bulk endpoint); all four declared complexity layers plus `derived_field_reconciliation` are covered; every one of the 60 error ids is either triggered by a corner instance or stubbed against a named §1.8 instance. All 27 stub citations resolve by name into `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, and no instance name collides across the two files.

## Work completed this session (after the errors chunk A)
- **errors chunk B**: 6 recipes (order-wide compliance hold blocking a clean sibling component; inspection round-open/state guards; the 4th round refused after 3 failures with promised_date slipped to `2026-11-29T00:00:00Z` and priority_score 25.00; single-use option review verbs; shop authorize/suspend state guards; void-then-re-register proving the duplicate guard counts only ACTIVE rows) + 8 stubs.
- **rbac (6)**: the two shared sampling endpoints' unequal role sets; the priority-20 role gate outranking business checks on peers' verbs; AuthorizedShop containment separating `ERR_ROLE_NOT_PERMITTED` (p20) from `ERR_SHOP_IDENTITY_MISMATCH` (p25); and the three segregation-of-duties shapes — sign≠measure, measure==round owner, option approve≠creator.
- **cross_cutting (7)**: one OCC instance per §1.2.1 rule (billet cut, option selection, and the refinish-loop finish run where a second create is a legal product operation so only the stale version may refuse it), the selector tie-break by earliest reservation `starts_at` (BO-3 created last must win over BO-2, catching a `created_at`/id fallback), plus 3 stubs.
- **consistency_model (1)**: `immediate` asserted across the create body, the parent GET and the reverse-FK list of one write.
- **SCAFFOLD.yaml consistency fixes** (needed to make catalog claims groundable): `OptionSelection.created_by_user_id` + the approve-side SoD precondition; the `QC_HELD -> SCRAPPED` side effects no longer double-count an already-QUARANTINED billet and now clear `qc_hold_reason` so `clear-compliance-hold` is reachable; an `INSPECTION -> INSPECTION` self-loop with `rework_round_count < MAX_REWORK_ROUNDS (3)` so `ERR_INSPECTION_ROUND_OPEN` and `ERR_MAX_REWORK_EXCEEDED` surface instead of `ERR_BUILD_STAGE_INVALID`.
- **Ledger-semantics audit of the new asserts**: `board_feet_available` is uncut stock only, so cut-but-unassigned wood belongs in `board_feet_unassigned`; corrected three asserts, renamed `board_feet_kerf_lost` → `board_feet_kerf_loss`, and rewrote the lot-rejection note to the scaffold's own reading (available 0.00 / scrapped 99.10 / kerf_loss 0.90 = 100.00 received), matching what §1.8's rejection cascade asserts.
- Verified no forbidden concurrency vocabulary in any of the three files, and that the sibling-task isolation constraint was honored throughout (no reads, lists, or greps outside this task directory and the skill's own files).

## Step 3: Copy shared files — 2026-09-03T21:35:57.483Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T22:00:00.000Z

PRD generation is complete.

**Output:** `.../workspace/PRD.md` — **545 lines**, ending at a real section boundary: last heading is `## 5. Error Code Catalogue` (line 468), whose final row is `` | `ERR_DEPOSIT_INSUFFICIENT` | 402 | ``. No audit footer, no contract-report section, no sibling files created.

**Structure:** §1 Introduction; §2 with twelve subsections (identity/RBAC, the byte-identical §2.2 response-structure block, pagination, identity and immutable reference data, logical clock, the 23-rung validation ladder with all four priority pairs, stale-version guards, rounding, the two interval semantics, the three conservation invariants, segregation of duties, cascades); §3 with nine workflow subsections (rooms and humidity cascade, tonewood receipt and CITES, billets and the wood ledger, specs/stations/next-job selector, parts and the rework loop, commercial dimension, assembly and cure clock, setup inspection and serialization, warranty and export); §4 with an 84-row endpoint table; §5 with a 71-row error table.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 142 required, 142 present, 0 missing   (158 field entries; 142 unique names incl. id/created_at/updated_at/version)
- endpoints[].input: 92 required, 92 present, 0 missing
- endpoints[] path params: 15 required, 15 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 23 checked, 23 expressed in prose, 0 missing (ladder rungs 10-88 numbered in §2.6; priority pairs P1 state>climate, P2 compliance>money, P3 window-conflict>capacity, P4 compliance>compatibility each stated as an explicit outranking)
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (operation + expected_build_order_version / expected_tonewood_lot_version + ERR_STALE_VERSION + HTTP 412 all named in §2.7), 0 missing
- state_machines[].transitions: 84 checked, 84 fully expressed, 0 missing (incl. both BuildOrder dimensions, the INSPECTION self-loop, the KILN_DRYING self-loop, the two creation branches on cites_appendix, and all four cascade links)
- calculations[]: 12 checked, 12 fully expressed with constants, evaluation order, rounding points and worked examples, 0 missing (dual variants PROVISIONAL/BINDING and NOMINAL/ACTUAL each given both input sets; forbidden readings — sum-then-multiply, tier-from-declared-value — explicitly ruled out)
- validations[] conditions: 23 checked, 23 matchable to error_id in prose, 0 missing; all 71 error_ids appear in §1-§4 narrative, not only in the §5 table
- endpoints[].side_effects / applies_to: 84 endpoints checked, all side effects and applies_to scopes expressed, 0 missing
- entities[].fields[] structured content: 142 checked, defaults/ranges/initial values reconstructible from prose (all 42 scaffold defaults stated concretely), 0 missing
- sibling-branch symmetry: 31 groups checked (25 multi-sibling from-states, 4 priority pairs, 2 dual-variant calculations), 31 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3):
- backticked tokens in §3: 1121
- tokens starting with "/": 0
- bare HTTP methods: 0
- method+path combinations: 0
Status: PASS
```

Also verified mechanically: no operator syntax (`>=`, `==`, `->`, `max(`, `round_half_up`, …) and no fuzzy words ("approximately", "roughly", "conservatively") anywhere in §1-§3; §2.2 matches the fixed block byte-for-byte. Two full paths appear in §2.4 to explain left-to-right path-then-body resolution order, which Contract 3 permits (it polices §3 only).

**Ambiguities resolved (worth flagging to the scaffold owner):**
1. `StorageRoom.latest_rh_pct`/`latest_temp_c` — the entity table says they equal the targets until the first reading, the create-endpoint description says null. Adopted the entity-table reading, since the cure calculation samples those fields.
2. `build_priority_score`'s prose parenthetical about saturation is arithmetically inconsistent with its own formula; the formula was written precisely and the consequence of a negative `days_out` stated instead.
3. Room certification with `latest_rh_pct` still outside the band: the scaffold names no code, so `ERR_ROOM_CLIMATE_OUT_OF_SPEC` (which exists in the catalogue) was used.
4. `FinishRun.finish_system` "MUST equal BuildOrder.finish_system" has no dedicated error; documented as `ERR_INVALID_REQUEST` since it is a body-field constraint.

The error catalogue is 71 entries (an earlier working note of 60 was wrong). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced.

**Orchestrator truncation check (per run instructions):** `tail -25` confirms PRD.md ends on the final complete row of the §5 error table — a real section boundary, not mid-sentence. 545 lines / 126099 bytes. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T23:07:35.357Z

Test generation is complete. Both output directories sit directly under the task root; `workspace/implementation/` was never read or written.

**Totals: 158 tests, 9 helper modules (2521 lines) + conftest + 18 test files (5385 lines).**

`test_helpers/` (unchanged this session): `types.py` 11, `api_errors.py` 201, `test_users.py` 119, `api_client.py` 412, `constants.py` 270, `assertions.py` 197, `factories.py` 503, `fixtures.py` 796, `__init__.py` 12.

`test_suite/`: `conftest.py` 42; `test_01` 171, `test_02` 208, `test_03` 217, `test_04` 215, `test_05` 298, `test_06` 302, `test_07` 286, `test_08` 185, `test_09` 172 (queue A, 58 tests); `test_10_corner_entities` 469, `test_11_corner_state_machines` 578, `test_12_corner_calculations` 291, `test_13_corner_validations` 374, `test_14_corner_endpoints` 255, `test_15_corner_errors` 645, `test_16_corner_rbac` 347, `test_17_corner_cross_cutting` 314, `test_18_corner_consistency` 58 (queue B, 100 tests).

**Design-index coverage.** 99 live instances exist across both indices (29 difficulty + 70 corner); 98 are translated, each test carrying exactly one verbatim `Design:` line as the last line of its docstring. All 27 `excluded_because:` stubs are untranslated. One live instance was deliberately skipped, not weakened: `Corner/validations/a_schema_violation_outranks_the_state_check_on_the_same_call` demands 422 `ERR_INVALID_REQUEST` when `reason` is omitted from lot rejection, but PRD line 393 makes `reason` optional, so the outcome is not uniquely derivable.

**Verification run at the end.**
- `pytest --collect-only`: 158 tests collected, no import or fixture-resolution errors.
- Machine-checked every docstring: exactly one `Design:` tag, last line, resolving to a live (non-stub) instance — 0 failures.
- Machine-checked all 158 PRD citations against `workspace/PRD.md` after whitespace normalization — 0 non-verbatim quotes. This caught one pre-existing defect in `test_05_priority_pairs.py`, a citation that began mid-sentence ("The order's `deposit_applied_cents`…"); it now quotes the full sentence from PRD line 373.
- Machine-checked every `F.`/`A.`/`X.`/`C.`/`U.`/`E.`/`api.` attribute and every fixture parameter against the actual helper modules — 0 missing names.
- No scaffold vocabulary or scaffold section numbers appear in generated code.

**Two design literals overridden as PRD-contradicted** (assertion corrected to the PRD-true value rather than dropped or weakened): the `errors` finish-run instance's `fb1_occupied_slots_during_buffing: 1` (PRD line 203 scopes `occupied_slots` to a booth-hold window that has already closed by the buff instant), and the `rbac` sampling instance's `lot_status_after: "RECEIVED"` (PRD line 235 moves a `RECEIVED` lot to `KILN_DRYING` on its first moisture reading, so the test asserts `KILN_DRYING`).

## Step 6: Generate implementation — 2026-09-03T23:07:35.357Z

The implementation is complete, boots from `bash start.sh`, and passed four end-to-end smoke runs plus automated endpoint/RBAC/error-catalogue cross-checks.

## Output: `.../workspace/implementation/`

Per-file line counts (3468 total):

| file | lines | file | lines |
|---|---|---|---|
| `start.sh` | 10 | `routes/rooms.py` | 90 |
| `requirements.txt` | 1 | `routes/lots.py` | 179 |
| `app.py` | 86 | `routes/billets.py` | 131 |
| `store.py` | 162 | `routes/stations.py` | 178 |
| `errors.py` | 106 | `routes/components.py` | 227 |
| `envelope.py` | 87 | `routes/catalog.py` | 173 |
| `auth.py` | 62 | `routes/orders.py` | 303 |
| `validate.py` | 212 | `routes/inspections.py` | 128 |
| `constants.py` | 129 | `routes/finish.py` | 216 |
| `calc.py` | 274 | `routes/service.py` | 190 |
| `domain.py` | 265 | `routes/exports.py` | 171 |
| `serialize.py` | 87 | `routes/__init__.py` | 1 |

## Verification performed (server on `PORT=18612`, killed only by recorded PID; port confirmed free afterwards)

- **Endpoint coverage**: parsed the PRD §4 table and diffed against Flask's url_map — **0 missing**, 0 extra (besides Flask's `/static`).
- **RBAC**: probed all 84 endpoints × 10 roles against the PRD's authorized-role column — **0 mismatches**.
- **Error catalogue**: all **71** PRD §5 error ids present with the exact HTTP statuses, and every one is actually raised somewhere in the code.
- **Worked examples reproduced exactly**: provisional 886185 / binding 716610 (with the MASTER row force-rejected at lock); option line 175500; nominal yield 49.85 vs actual 10.00 with kerf 0.30; NITRO 12-coat hold 412 h and `cure_hours` 408 → `cure_ready_at` 2026-08-22T09:00:00Z; POLY 3-coat floor 48 h; export tier-2 fee 7883; deviation score 10.00 → PASS; serial `LP-STD-2026-00001`; 60-month coverage 2026-08-22 → 2031-08-22T00:00:00Z; cancel forfeit capped at the held balance.
- **Cascades**: booth excursion → run `CURE_SUSPENDED` (+`cure_suspend_started_at`) → order `FINISH_HELD` → future `HELD` reservation `RELEASED` with the station's 60 minutes moved from `held_minutes` to `released_minutes`; resume banked 750 minutes and pushed `cure_ready_at` to 2026-08-22T21:30:00Z. Lot rejection → billet `QUARANTINED`, component `QC_HELD`/`PROTECTED_SPECIES`, order `COMPLIANCE_HOLD` with `stage_before_compliance_hold` recorded, uncut board feet moved to `board_feet_scrapped`; clear-compliance-hold refused until the impounded part was scrapped, then restored the saved stage.
- **Ladder/precedence spot checks**: `ERR_STALE_VERSION` 412 on all three guarded creates, station buffer conflict 409, route on an out-of-spec room 409, thin deposit 402, SoD on option approve 403, `ERR_OPTION_FINISH_MISMATCH` 422 vs `ERR_OPTION_INCOMPATIBLE` 409, shop identity 403 on both the shop read and the unfiltered registration list, duplicate open shipment 409, release-before-serialization `ERR_BUILD_STAGE_INVALID`, `limit=101`/`offset=-1` → `ERR_INVALID_REQUEST` 422 (never clamped), unknown role → `ERR_UNAUTHENTICATED` 401, bad JSON → 422, unknown route → 404 envelope, wrong verb → 405 envelope.
- **No seeding**: every store dict is empty at import; a fresh boot returns `total_count: 0` on every collection. `ComponentSpec`/`OptionCatalog` representations carry only `id` + `created_at` (no `updated_at`/`version`), ids are bare UUIDs, audit timestamps have exactly 3 fractional digits while domain instants render to whole seconds.

Two deliberate interpretation calls worth flagging: `occupied_slots` and `warranty_claim_count` are implemented as read-time mirrors (per PRD §3.1's "read-only mirror" sentence and §3.9's "reflects the count of its ACTIVE registrations"), so voiding a registration does not bump the shop row's `version`; and finish-run rejection ignores the body's optional `reason` because `ExportShipment`-style reason fields do not exist on `FinishRun` in the scaffold.

**Orchestrator note:** verified `test_helpers/` and `test_suite/` landed at the task root (not under `workspace/`) — no relocation needed. Steps 5 and 6 were launched in a single assistant message, so the impl generator started before `test_suite/` existed on disk.

## Step 7: Run tests and iterate — 2026-09-03T23:30:50.221Z

All 8 parallel rounds pass 158/158. Exiting.

## Summary

**Iterations run:** 2 (each an 8-round parallel `setsid nohup` sweep, 158 tests/round). Iteration 1: 142/158 in all 8 rounds, 16 failures, byte-identical across rounds — fully deterministic, no flakiness or load-induced failures. Iteration 2: **158/158 in all 8 rounds.**

**Tests deleted:** none. No failing test was PRD-silent at the whole-test level; two individual assertions were removed under the partial-coverage rule (1c):

- `test_07_cross_entity_dependencies.py::test_a_measured_but_unsigned_round_does_not_earn_a_serial_number` — dropped `assert measured["verdict"] == "PASS"`. **Enum-membership-only / branch silence:** PRD says measuring "moves the round `OPEN → MEASURED` and computes its `deviation_score`" and names `verdict` writes only at creation (`PENDING`) and at signing (`PASS`/`FAIL`); nothing states a verdict write at measure time. Scaffold rule driving it: `Difficulty/cross_entity_state_dependency/assign_serial_requires_the_latest_inspection_signed_and_passing`. The test's actual `ERR_INSPECTION_NOT_SIGNED` assertion is untouched.
- `test_11_corner_state_machines.py::test_a_failing_score_drags_the_order_backwards_without_moving_the_money` — dropped `assert signed["inspector_user_id"] == "qi-frank"`. **Branch-asymmetric side effect:** PRD stamps `inspector_user_id` only on the PASS branch ("moves `MEASURED → SIGNED` … and `inspector_user_id` stamped with the signer"); the FAIL branch clause omits it. Scaffold rule: `Corner/state_machines/a_failed_inspection_pushes_the_order_back_to_setup`.

**Fixes applied to test_suite/** (no `test_helpers/` change was needed — the bugs lived in per-file local factories and assertions):

- `test_05_priority_pairs.py` (4 sites) + `test_07_cross_entity_dependencies.py` (1 site) — read the error id from `response.json()["data"]["error_id"]` instead of `["error"]`. PRD §2.2 puts `error_id`/`message` inside `data`; the raw-envelope reads were the only places bypassing `validate_error`, so they alone had the wrong shape (this was the `KeyError: 'error'` cluster).
- `test_13_corner_validations.py` — local `NITRO_ONLY_OPTION` factory used `option_group: "FINISH"`, which is not in PRD's enum (`TOP_WOOD, INLAY, HARDWARE, ELECTRONICS, NECK_PROFILE`); changed to `NECK_PROFILE`. The PRD-faithful server correctly 422'd the fixture's own catalog row before the test could exercise `ERR_OPTION_FINISH_MISMATCH`.
- `test_06_boundary_precision.py` — local helper `a_quoted_custom_order_at_eight_hundred_eighty_six_thousand` built only the approved ARTISAN vine line, which yields 716610, not the 886185 its name and both tests assert. Added the `PENDING_APPROVAL` MASTER top-wood selection so the order matches PRD's worked example (both statuses sit in the provisional input set) — which is what makes the 10% threshold land on the exact half cent 88618.5 the two boundary tests probe.
- `test_04_transitive_cascades.py` — `promised_date` expectations ignored the schedule push that `lock-options` performs (PRD: clock date + 60 base days + largest locked `lead_time_days` = 2026-08-01 + 105 = **2026-11-14**, later than the created 2026-10-01). Corrected to `2026-11-14` (first failure moves nothing) and `2026-11-28` (second failure slips a fortnight), and `priority_score` `87.50 → 60.00`, since 2026-11-28 is 98 days past the 2026-08-22 clock so the 90-day urgency term clamps to zero, leaving endorser 20 + custom-shop 15 + at-risk 25.

**Fixes applied to implementation/:**

- `workspace/implementation/routes/finish.py`, `create_run` — the booth-conflict scan passed a **run dict** where `domain.booth_overlaps` expects a `booth_id`, so `run["booth_id"] != booth_id` was always true and the overlap set was always empty. Both PRD §3.7 booth rules (`ERR_BOOTH_FINISH_INCOMPATIBLE`, then `ERR_BOOTH_CAPACITY_EXCEEDED`) were dead code; every conflicting booking succeeded. Replaced with `domain.booth_overlaps(booth["id"], hold_from, hold_until)`. This single bug caused 5 of the 16 failures.
- `workspace/implementation/domain.py`, `inspection_fail_cascade` — the escalation block was gated on `commercial_status in (CONFIRMED, OPTIONS_LOCKED)` in addition to the round count, so a third failure on an order already `AT_RISK` slipped nothing. PRD guards the block on the count alone ("if that count has reached two or more … `promised_date` advances by fourteen days, and `priority_score` is recomputed"); only the status move is a transition that can be already spent. Now the promise advances and the score refreshes on every failure at count ≥ 2, with the status move nested.

**Orchestrator verification (per memory of a prior false-clean claim):** independently re-read all 8 `results.$i.json` — every round reports `passed=158 total=158 failed=0`, files timestamped 23:28 (post-fix sweep). Artifacts confirmed present, not merely asserted.

## Step 8: Finalize PRD — 2026-09-03T23:35:19.248Z

Done. `PRD_FINALIZED.md` is a 3-line patch of `PRD.md`.

## Line counts
- `PRD.md`: 545 lines / `PRD_FINALIZED.md`: 545 lines — 3 of 545 lines revised (0.55% of lines; no lines added or removed). `diff` shows changes only at lines 251, 337, 343; file still ends at the §5 error-code table.

## Changes
- **§3.8 (measure)** — insert — pinned that the measurement call writes no verdict and no inspector: `verdict` stays `PENDING` and `inspector_user_id` stays null at that step, however the score comes out — `implementation/routes/inspections.py:95-103` (measure writes only the four figures, `deviation_score`, `status`).
- **§3.8 (signing, FAIL branch)** — insert — FAIL branch leaves `inspector_user_id` null; the signer stamp belongs to the PASS branch alone — `implementation/routes/inspections.py:117-125`.
- **§3.8 (failure cascade escalation)** — revise — the escalation block is guarded by `rework_round_count ≥ 2` alone: the fourteen-day `promised_date` slip and the `priority_score` recomputation fire on every such failure regardless of `commercial_status`, while only the `CONFIRMED/OPTIONS_LOCKED → AT_RISK` move is a spendable transition (an already-`AT_RISK` order keeps its status but still slips and re-scores) — `implementation/domain.py:248-260`.
- **§3.4 (priority-score refresh triggers)** — revise — trigger list widened from "when it escalates to `AT_RISK`" to "on every failed inspection round that fires the escalation block of §3.8 — whether or not that failure actually moves `commercial_status` to `AT_RISK`" — `implementation/domain.py:259`, `implementation/calc.py:199-201`.

No PRD edit for the other Step 7 items: the `error_id` envelope reads (§2.2 already pins `data.error_id`), the `option_group: "FINISH"` fixture (enum already pinned in §3.6), the `886185` fixture helper (§3.6 already pins the provisional input set as `PENDING_APPROVAL` + `SELECTED`), the `promised_date`/`priority_score` expectations in test_04 (§3.6 lock-options schedule push and §3.4 zero-clamp already determine 2026-11-14 / 2026-11-28 / 60.00, and `implementation/routes/orders.py:152-157` matches the prose), and the `finish.py` `booth_overlaps` fix (§2.9/§3.7 already pin closed-interval overlap, chemistry-before-capacity, and non-terminal = not `COMPLETED`/`REJECTED`; the fix restored PRD behavior rather than revealing silence).

## Per-edit pre-edit search log
1. **Edit 1 — subject: `verdict` / `inspector_user_id` writes at measure time.** (b) Enumerated every write and read of both fields: `grep -rn "verdict|inspector_user_id" implementation/` → `routes/inspections.py:48,50` (create: `PENDING` / null), `:70` (list filter over `VERDICTS`), `:99-103` (measure — no write), `:119-120` (sign PASS), `:124` (sign FAIL), `routes/orders.py:241` (serialization requires latest round `SIGNED` + `verdict == PASS`), `routes/components.py:163-171` (unrelated component-QC `verdict` request field), `serialize.py` (`public()` passthrough, no computed mirror). (c) Dropped an earlier draft phrasing "until the round is signed", because the FAIL branch also goes through the sign endpoint without stamping `inspector_user_id`; final wording scopes the claim to "at this step" so it says nothing about what signing does.
2. **Edit 2 — subject: `inspector_user_id` on the FAIL branch.** (b) Same enumeration as above; confirmed `inspector_user_id` is assigned at exactly one site (`inspections.py:120`, PASS only) and read nowhere, so a FAILED round keeps the creation-time null forever. (c) Kept the claim branch-local ("belongs to the passing branch alone") rather than asserting anything about later re-opened rounds, which are separate rows.
3. **Edit 3 — subject: the inspection-failure escalation block (round count, `promised_date`, `priority_score`, `commercial_status`).** (b) Read `domain.py:248-260` (cascade), `constants.py:125-127` (`MAX_REWORK_ROUNDS=3`, `REWORK_ESCALATION_THRESHOLD=2`, `REWORK_SLIP_DAYS=14`), `routes/inspections.py:126-127` (only caller), `routes/inspections.py:29-39` (`rework_round_count < 3` gate on opening a round), `routes/orders.py:246` (`AT_RISK → INVOICED` at serialization), `:100-159` (confirm/lock status moves), `calc.py:185-201` (`AT_RISK` scoring term), `routes/stations.py:78-94` (selector eligibility excludes nothing about `AT_RISK`), PRD §3.6 cancellation basis (`OPTIONS_LOCKED` or `AT_RISK`). (c) Deliberately left the unconditional `build_stage = SETUP` and `rework_round_count += 1` prose untouched (impl sets them unconditionally, including from stages PRD's `INSPECTION → SETUP` phrasing does not name — a path Step 7 never exercised, so I did not narrow or widen it); phrased the status-move exception as "whatever the order's `commercial_status` happens to be" instead of enumerating statuses, so no reachability claim is made.
4. **Edit 4 — subject: the set of `priority_score` refresh triggers.** (b) Enumerated every write: `routes/orders.py:69` (init 0), `:75` (create), `:122` (confirm), `:157` (lock-options), `domain.py:259` (failure escalation), `routes/stations.py:83` (selector recomputes in place, no `touch`), `:141` (reservation snapshot, never re-synced); confirmed cancellation (`routes/orders.py` cancel path) does **not** refresh, matching the existing PRD list. (c) Phrased the new trigger as "every failed inspection round that fires the escalation block of §3.8" rather than "every failed round", since the impl refreshes only inside the `count ≥ 2` branch; left the "clock is not a trigger" and "selector reads it" clauses verbatim so §2.5's lazy-refresh sentence stays consistent.

**Orchestrator verification:** independently ran `diff PRD.md PRD_FINALIZED.md` — exactly 3 changed lines (251, 337, 343), no additions or deletions, and `tail` confirms the file still ends on the final §5 error-table row. Not byte-identical to PRD.md, so the patch really was applied.

## Step 9: Complete PRD — 2026-09-04T00:08:18.592Z

Run as **three sequential file-partitioned passes** over `implementation/` rather than one scan, because a single-pass Step 9 on a 24-module implementation has previously produced a byte-identical no-op. Pass A did the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes B and C edited the same file in place and were each given the prior pass's hand-off notes.

**Source:** `PRD_FINALIZED.md` (545 lines) → **`PRD_COMPLETED.md` (547 lines)**, `diff | wc -l` = 245, not byte-identical, all 29 headings intact, still ends on the final §5 `ERR_DEPOSIT_INSUFFICIENT` table row. Net +2 lines (one §5 preamble paragraph); everything else is in-paragraph inserts/revisions, no new sections.

**Totals across the three passes: 72 changes — 57 ambiguity-pins, 15 mismatch-revisions.**

### Pass A — app/store/envelope/errors/auth/validate/constants/serialize/rooms/lots/billets/stations (25 pins, 5 mismatches)
- §2.1 — insert — ambiguity — whitespace-only `X-User-ID` counts as empty → `ERR_UNAUTHENTICATED` — auth.py:38
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — envelope.py:11,21
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the real wall clock, not the logical clock — envelope.py:27, store.py:79
- §2.3 — insert — ambiguity — empty `limit`/`offset` → default, non-integer → 422, whitespace/leading `+` tolerated, `offset` unbounded (past-end = empty page), undeclared query params ignored — envelope.py:59-79
- §2.3 — insert — ambiguity — code orderings compare raw strings; ties fall back to insertion sequence, never `id` — store.py:133-138, stations.py:88,165
- §2.3 — insert — ambiguity — empty filter = absent, out-of-enum filter → 422, id filters are opaque exact matches (nonexistent → empty page, not 404) — validate.py:177-211
- §2.4 — insert — ambiguity — `created_at`/`updated_at` minted from the wall clock, not the logical clock — store.py:79-82
- §2.4 — **revise — mismatch** — PRD claimed the path row must exist "before anything in the body is examined"; impl runs the whole schema rung first — rooms.py:69-72, lots.py:101-103, catalog.py:69-75
- §2.5 — insert — ambiguity — clock reply is `data.current_utc` only; domain instants render to whole seconds with `Z`, fractional input discarded; only audit columns + `api_request_timestamp` carry 3 digits — app.py:41-44, store.py:50-76
- §2.5 — insert — ambiguity — the clock endpoint inspects neither header — app.py:38-44
- §2.6 rung 4 — insert — ambiguity — absent/empty body = `{}`, non-object/non-JSON → 422 (not 400), explicit `null` = absent, undeclared body fields ignored, non-string body FK caught here not at rung 7 — validate.py:17-33,145-154
- §2.6 rung 5 — insert — ambiguity — `starts_at >= ends_at` yields `ERR_INVALID_WINDOW` even though it also fails rung 4's positive-`duration_minutes` — stations.py:109-114
- §2.6 precedence bullet — **revise — mismatch** — there is no station capacity ceiling at all; the only capacity ceiling is a booth's `capacity_slots` — stations.py:100-145, finish.py:70
- §2.8 — insert — ambiguity — decimals serialise as plain JSON numbers (so `55.0` is legal), money/bp as integers — store.py:143-150
- §3.1 — insert — ambiguity — `rh_pct`/`temp_c` unbounded; `last_reading_at` null until first sample, stamped from the logical clock — rooms.py:70-73, domain.py:145-149
- §3.2 — insert — ambiguity — a lot's `storage_room_id` naming a non-`DRY_STORE`/`KILN` room is 422, raised before `lot_code` uniqueness; quarantine refusal comes after — lots.py:48-52
- §3.2 — insert — ambiguity — `permit_number` stored verbatim/null on both branches and verifies nothing; both yields plus `board_feet_cut` derived on read — lots.py:46-72, serialize.py:27-32
- §3.2 — insert — ambiguity — lot-rejection `reason` validated non-empty but never persisted — lots.py:119
- §3.2 — **revise — mismatch** — an order already in `COMPLIANCE_HOLD` is skipped by the rejection cascade — domain.py:239-243
- §3.2 — insert — ambiguity — moisture-reading input bounded 2.0–30.0 like receipt — lots.py:135
- §3.3 — insert — ambiguity — `parent_billet_id` need only exist; a resaw still draws board feet + kerf from the lot and leaves the parent untouched — billets.py:30-58
- §3.4 — insert — ambiguity — a station's room `room_type` is unconstrained — stations.py:29-32
- §3.4 — insert — ambiguity — reservation `priority_score` snapshot is the stored score, null with no `build_order_id` — stations.py:141
- §3.4 — insert — ambiguity — the selector's score refresh writes in place without moving `updated_at`/`version` — stations.py:83
- §3.4 — insert — ambiguity — a `HELD` window counts whether past or future — stations.py:76-84
- §4 preamble — insert — ambiguity — trailing slashes resolve to the same endpoint — app.py:30
- §4 `/tonewood-lots/{id}/reject` — revise — ambiguity — "recording a reason" → validated but not persisted — lots.py:119
- §4 `POST /stations` — **revise — mismatch** — `capacity_minutes_per_day` does not exist; row now names `room_id`/`changeover_minutes` — stations.py:20-43
- §4 `POST /station-reservations` — **revise — mismatch** — "window conflict before daily capacity" → overlap is the only check — stations.py:100-145
- §5 preamble — insert — ambiguity — `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` sit outside the ladder and precede authentication — app.py:52-81

### Pass B — calc/domain/components/catalog/orders/inspections (20 pins, 3 mismatches)
- §2.3 — insert — ambiguity — boolean filters accept `true`/`false`/`1`/`0` in any case, else 422 — validate.py:193, orders.py:94
- §2.6 rung 8 — insert — ambiguity — natural-key codes are 1–64 chars (`room_code` 32, `model_code` 16), enforced at the schema rung — orders.py:36-37, catalog.py:24
- §2.7 — insert — ambiguity — an echoed `expected_*_version` carries no positivity bound; zero/negative is `ERR_STALE_VERSION`, not a schema violation — catalog.py:71
- §3.1 — insert — ambiguity — `OUT_OF_SPEC → QUARANTINED` carries `out_of_spec_since` over untouched; only certification clears it — domain.py:167-170
- §3.5 — insert — ambiguity — a component's `build_order_id` need only exist; `build_stage` not examined at creation — components.py:45-50
- §3.5 — **revise — mismatch** — the lot-`RELEASED` check sits *after* species and grade; a `DEPLETED` lot + low grade reports `ERR_GRADE_BELOW_MINIMUM` — components.py:60-67
- §3.5 — insert — ambiguity — `measured_thickness_mm` required, > 0, no upper bound, no fixed scale — components.py:107
- §3.5 — insert — ambiguity — route/hand-shape refuse `ERR_COMPLIANCE_HOLD_ACTIVE`, weighed after climate and before the `component_id`/station-type comparisons — components.py:121-123
- §3.5 — insert — ambiguity — the disposition role split is decided from the body before the part is looked up, so it outranks existence and status — components.py:196-202
- §3.5 — insert — ambiguity — cancellation never clears `qc_hold_reason` (unlike a QC scrap) — orders.py:286-290
- §3.5 — insert — ambiguity — the owning order's row is written on all three protected-species recomputes even when the posture is unchanged; a part with no order writes none — components.py:184-187,223-226
- §3.6 — insert — ambiguity — `incompatible_option_codes` entries stored verbatim, never resolved against the catalog — catalog.py:29-30
- §3.6 — insert — ambiguity — an echoed body `build_order_id` is validated non-empty then ignored; configuration has no `commercial_status` gate — catalog.py:74, 66-108
- §3.6 — insert — ambiguity — selection-reject `reason` non-empty when present, discarded — catalog.py:158
- §3.6 — insert — ambiguity — on approve/reject the selection's own status is weighed before the order's `commercial_status` — catalog.py:135-142,160-167
- §3.6 — insert — ambiguity — `deposit_cents` required integer, zero allowed, negative rejected — orders.py:104
- §3.6 — insert — ambiguity — release-components tests build stage first, so a past-`DRAFT` order reports `ERR_BUILD_STAGE_INVALID` — orders.py:166-171
- §3.6 — insert — ambiguity — cancel `reason` non-empty when present, discarded — orders.py:278
- §3.8 — **insert — mismatch** — `measure` reads its body only after the status and owner checks, a deliberate departure from §2.6's schema-first rung — inspections.py:79-86
- §3.8 — revise — ambiguity — `build_stage` assigned `SETUP` unconditionally; escalation runs status-move → 14-day slip → score refresh, so the refreshed score carries the `AT_RISK` points and the new promise — domain.py:250-259
- §3.8 — **insert — mismatch** — the serial guard is weighed before the stage check, so a second attempt reports `ERR_SERIAL_ALREADY_ASSIGNED`, never `ERR_BUILD_STAGE_INVALID` — orders.py:231-236
- §4 `/cancel` and `/option-selections/{id}/reject` rows — revise — ambiguity — `reason` validated but not persisted

Pass B's verdicts on pass A's hand-offs: discarded `reason` confirmed and fixed; the `quantity` ceiling of 4 was **already** pinned in §3.6 (no edit); §3.8's round-count guard already matched (Step 8's work), so only the intra-escalation ordering and the unconditional `SETUP` were added; §2.9's `HELD`/`CONSUMED` and booth non-terminal wording already correct.

### Pass C — finish/service/exports (+ their serialize/calc paths) (12 pins, 7 mismatches)
- §2.6 rung 3 — insert — mismatch — rung 3 sits above rung 6 everywhere except reading one registration, where the comparison is against the fetched row, so a shop gets `ERR_WARRANTY_REGISTRATION_NOT_FOUND` — service.py:151-157
- §3.7 — insert — ambiguity — the `finish_system`-vs-order comparison (`ERR_INVALID_REQUEST`) is weighed after the body FKs resolve but above stage/version/climate/room-type — finish.py:49-60
- §3.7 — **revise — mismatch** — booking no longer "increments the booth's `occupied_slots`"; it writes nothing to the booth row and the room's `updated_at`/`version` do not move — finish.py:74-91, serialize.py:9-24
- §3.7 — insert — ambiguity — a new run opens with `spray_completed_at`/`cure_hours`/`cure_ready_at`/`cure_suspend_started_at` null and `cure_suspended_minutes` 0 — finish.py:80-84
- §3.7 — revise — ambiguity — `occupied_slots` is neither an independent constraint nor a stored column any operation increments or decrements — serialize.py:9-24
- §3.7 — insert — ambiguity — banked minutes are complete minutes **truncated downward**, explicitly not §2.8's half-up (90 s banks 1, 50 s banks 0) — finish.py:150-152
- §3.7 — insert — ambiguity — the climate rung is weighed before the cure clock, so a drifted booth reports `ERR_ROOM_CLIMATE_OUT_OF_SPEC`, never `ERR_CURE_NOT_COMPLETE` — finish.py:171-174
- §3.7 — **revise — mismatch** — complete no longer "decrements `occupied_slots`"; completion consults no climate at all — finish.py:180-193
- §3.7 — **revise — mismatch** — reject's `reason` non-empty when present, validated then discarded; no `occupied_slots` write, no climate check — finish.py:196-206
- §3.9 — insert — ambiguity — a `NONE` `authorization_level` is 422 decided from the body alone, even for an unknown `shop_id`; suspend's `reason` given the discarded-shape wording — service.py:77-79,94
- §3.9 — insert — ambiguity — for a shop caller the identity comparison reads the raw body first, so an absent/non-string `registering_shop_id` is `ERR_SHOP_IDENTITY_MISMATCH` rather than the schema error a manager would get; `purchase_date` never compared with the clock — service.py:110-114,121
- §3.9 — insert — ambiguity — `ERR_WARRANTY_ALREADY_REGISTERED` outranks both other rules despite being stated last, and `ERR_SHOP_NOT_AUTHORIZED` outranks `ERR_SERIAL_MISMATCH` — service.py:124-134
- §3.9 — **revise — mismatch** — `warranty_claim_count` counts **registrations, not claims**, derived at read time, so creating one leaves the shop row untouched — serialize.py:75-79
- §3.9 — **revise — mismatch** — void's `reason` shape pinned; voiding does not write the shop row, the read-time count simply falls — service.py:177-190
- §3.9 — insert — ambiguity — a shipment may be opened at **any** `build_stage`; serialization bites at release — exports.py:37-67
- §3.9 — insert — ambiguity — a null `binding_quote_total_cents` reads as zero (worked floor case 0/3000/27/3027); the attach re-run reads goods value live from the order but the CITES endorsement from the shipment snapshot — exports.py:26-34,90-110
- §3.9 — insert — ambiguity — an attach omitting the permit on a shipment that requires none retains the prior number; reject-docs `reason` is mandatory non-empty (the only mandatory `reason` in the spec) and still discarded — exports.py:106-107,117
- §3.9 — insert — ambiguity — the contributing set is the §3.5 walk recomputed **live** at release, not the shipment snapshot; the permit and segregation walks are two separate passes — exports.py:127-159, calc.py:206-220
- §4 void row — **revise — mismatch** — dropped "decrement the shop's `warranty_claim_count`" in favour of the read-time count — service.py:188-189

Pass C's verdicts on pass B's hand-offs: `occupied_slots` confirmed as a real mismatch and fixed in four places; the `finish.py` check ordering turned out to *match* §2.6's rungs (only §3.7's narrative order misled) and the `finish_system` equality check was found to sit above all four; discarded `reason` confirmed for finish-reject/suspend/void, with the new finding that `exports.py:117` makes it *mandatory*; export re-pricing confirmed and sharpened (snapshot endorsement, live goods value); `warranty_claim_count` confirmed to count registrations.

No pass reverted or contradicted an earlier pass, and none reported believing an earlier edit wrong.

**Orchestrator verification.** `wc -l`: PRD.md 545 → PRD_FINALIZED.md 545 → PRD_COMPLETED.md 547. `cmp` confirms PRD_COMPLETED.md is **not** byte-identical to PRD_FINALIZED.md (the prior-run failure mode this partitioning guards against); `diff | wc -l` = 245; `grep -c '^#'` = 29 headings, matching PRD.md, so no section was dropped; `tail` ends on the final §5 error-table row. Also confirmed via `stat` that no file under `implementation/`, `test_suite/`, or `test_helpers/` was modified after the 23:28 clean sweep — Steps 8 and 9 touched only `workspace/*.md` — so the 8×158/158 result stands as the final verified state. Pipeline complete.
