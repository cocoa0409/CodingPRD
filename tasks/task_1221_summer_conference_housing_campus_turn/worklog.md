# Worklog — task_1221_summer_conference_housing_campus_turn

## Step 1: Create Task Directory — 2026-08-12T00:37:00.000Z

Task directory pre-assigned and already present: `tasks/task_1221_summer_conference_housing_campus_turn/` with `workspace/` subdirectory. Step 1 treated as done per pipeline input; no auto-index scan performed.

## Step 2: Generate Scaffold — 2026-08-12T01:27:00.000Z

All three scaffold artifacts are generated, lint-clean, and verified on disk under `/home/ubuntu/github/CodingPRD/tasks/task_1221_summer_conference_housing_campus_turn/`.

## Design summary (Expert+ difficulty)

**Archetype**: temporal windowing (primary) + quota/allocation (secondary), with layers: cascading side effects, dual-variant calculation, rate/threshold triggers, optimistic concurrency. Building and Room machines are cyclic across seasons; TurnTask has a rework loop; BackgroundScreening has an appeal-reversal loop.

**Key hard mechanics**:
- Bed-night billing: marginal tier at bed-night index > 100, minor surcharge rounded per-night *before* flat Fri/Sat weekend premium, provisional-vs-final divergence (planned vs actual nights, NO_SHOW flat 4500).
- Damage charge with pinned per-unit rounding (round-half-up per unit, then multiply, then sum, then one admin fee) + estimate/assessed variants.
- Revenue waterfall with pinned evaluation order (overhead 12% of gross → reserve 8% of net → ops absorbs drift).
- Two interval semantics: half-open datetimes + 24h/30h linen-tier turn gaps on Room vs inclusive buffered date windows + fall-opening deadline on Building.
- Two OCC rules (revision supersede on group version; window create on building version), plus conditional RBAC escalation at turn rework_count >= 2.

## Verification results

- YAML: all three files parse with `yaml.safe_load`.
- `scaffold_lint.py` verdict: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (1020 calls scanned; initial 16 FK_REVERSE_UNREACHABLE findings were fixed by renaming path params to `{id}` and adding 7 single-resource GET endpoints.)
- SCAFFOLD.yaml contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` keys; each design file has exactly its single top-level key.
- All numeric asserts were pre-computed as literals (e.g., 32650, 462000/542400, 7501 vs 7500, 4320/2534/29146, cancellation tiers 0/14400/36000, key fees 0/1500).
- Instance names unique across both design files.

## Counts

| Metric | Count |
|---|---|
| Entities | 14 |
| State machines | 13 |
| Calculations | 7 |
| Validations | 33 |
| Endpoints | 80 |
| Errors | 33 |
| Roles | 6 (+2 OCC concurrency rules) |
| Difficulty instances | 19 (all 9 rules ≥ 2; combinatorial_formula has 3 covering modes a/b/c) |
| Corner instances | 56 (52 with recipes + 4 excluded_because stubs) |

## File sizes

- `SCAFFOLD.yaml` — 111,417 bytes
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 107,971 bytes
- `SCAFFOLD_CORNER_DESIGN.yaml` — 184,749 bytes

## Step 3: Copy Shared Files — 2026-08-12T01:28:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1221_summer_conference_housing_campus_turn/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-12T01:41:00.000Z

PRD generated and verified at `/home/ubuntu/github/CodingPRD/tasks/task_1221_summer_conference_housing_campus_turn/workspace/PRD.md`. The two forbidden design files and all sibling task directories were never touched.

**Output summary**
- Lines: 314 | Size: 57,811 bytes
- Sections: 1. Introduction (2 paragraphs) · 2. Global Specifications (2.1 Roles/RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Logical Clock, 2.6 Request Validation Order, 2.7 Optimistic Concurrency Control, 2.8 Hierarchical Consistency & Building Ledger Counters, 2.9 Monetary Precision, 2.10 Nested Resource Retrieval) · 3. Business Logic (10 domain-derived subsections: building release lifecycle, contract intake, screening/minor policy, rooming lists, guest stays, the turn, linen/keys, damage/disputes, billing, maintenance + revenue allocation) · 4. Endpoint Definitions (80 rows, 4 columns) · 5. Error Code Catalogue (33 rows, 2 columns).

**Coverage audit (Zero-Silence Rule)**
- Contract 1 — Field-Name Coverage: PASS. 83/83 entity fields, 45/45 endpoint input identifiers, 9/9 query params, 1/1 path param — all present verbatim in backticks.
- Contract 2 — Rule Coverage: PASS. All 33 error IDs named in prose near their triggers; both OCC rules expressed with `expected_conference_group_version`/`expected_building_version` + `ERR_STALE_VERSION`/412; all 55 state-machine transitions across 13 machines rendered with preconditions and side effects (54 state values present); all 7 calculations translated to precise prose with every constant (4500/3900/100 bed-night tiers, 15% minor surcharge, 400¢ weekend premium, 2%/0.40-floor/2500¢ damage, 12%/8% waterfall, 24/30-hour turn windows, 2-grace-day/1500¢-per-day/7500¢-cap/5000¢ key fees, 31/15-day 20%/50% cancellation tiers, 3200/1600 linen); validation priority orderings stated per endpoint (confirm gauntlet, revision gauntlet, check-in, maintenance confirm, payment); all `applies_to` scopes enumerated; `common_fields: false` exception for RoomingListRevision stated explicitly.
- Contract 3 — §3 Path Purity: PASS. 486 backtick tokens scanned in §3, zero paths/methods; HTTP contract lives only in §4.
- Contract precision: §2.2 byte-identical to the canonical block; pagination defaults (10/1/100/0, `created_at` ascending); no pseudocode operators or fuzzy words; endpoint table = 80/80 paths; error table matches the catalog exactly (id + HTTP status).

## Step 5: Generate Unit Tests — 2026-08-12T02:11:00.000Z

Generation complete and fully verified. Summary below.

## Deliverables

**test_helpers/ (9 modules, all present)**
| file | bytes |
|---|---|
| `__init__.py` | 1,012 |
| `types.py` | 7,516 |
| `api_client.py` | 15,824 (70 endpoint methods, one per PRD endpoint incl. `/_clock/set_current_utc`) |
| `api_errors.py` | 3,707 (33 error IDs + HTTP map, registered with framework) |
| `assertions.py` | 6,991 |
| `factories.py` | 3,681 |
| `constants.py` | 1,558 |
| `test_users.py` | 1,843 (shared opaque-role headers + `make_coordinator_headers(group_id)` for the entity-backed ClientCoordinator) |
| `fixtures.py` | 14,764 (season progression, group/revision hierarchy, confirmed→in-house→departed→paid lifecycle, NEEDS_TURN spawn, screening clear/flag, clock) |

**test_suite/ (conftest.py + 13 files, 88 tests)**
- test_01 building season (9), test_02 group lifecycle (6), test_03 rooming revisions/OCC (7), test_04 booking windows (3), test_05 guest stays/cascades (8), test_06 turn tasks (4), test_07 screening (6), test_08 billing (13), test_09 validation order/finalize (5), test_10 damage (7), test_11 keys/linen (8), test_12 maintenance/allocation (8), test_13 RBAC (4)

**Queue split:** 38 queue-A (all 19 difficulty instances × exactly 2 tests) + 50 queue-B. Every test carries exactly one `Design:` tag as the last docstring line; automated audit confirms tags resolve to real instances/sections in the source yamls, all 4 `excluded_because` stubs are untranslated with resolvable cross-references, and every test's PRD citation has an ≥8-word fragment that literally greps in `workspace/PRD.md`. All files pass `py_compile`; no skip/xfail markers; no scaffold references in comments.

## Skipped instances (2, both queue B, gaps left as gaps)
1. **`Corner/entities/system_minted_fields_input_ignored`** — unique-derivability failure: the instance asserts `version == 1` at creation, but the PRD says only version "starts at its initial value on creation" without pinning the value, and is silent on whether client-supplied system fields are ignored vs. rejected.
2. **`Corner/validations/screening_expired_at_confirm`** — threshold silence: the PRD names `SCREENING_VALIDITY_MONTHS` but never states its value (12), so the asserted expiry outcome is not derivable by a PRD-only reader.

## One deliberate correction
`Corner/cross_cutting_layers/cascading_provisional_recompute_on_supersede`: the yaml's assert block is internally inconsistent — it supersedes a 4-night stay to a 2-night stay (its own setup computes 2 × 4500 = 9000) but asserts 4500. The PRD uniquely derives 9000, so the emitted test asserts `provisional_total_cents == 9000`.

## Step 6: Generate Implementation — 2026-08-12T02:11:00.000Z

Implementation complete and verified. Summary:

## Deliverables — `workspace/implementation/`

| File | Size | Purpose |
|---|---|---|
| `start.sh` | 388 B | Guarded pip install + `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 11 B | flask>=2.2 |
| `app.py` | 1,260 B | Flask app, ApiError/404/405/500 envelope handlers, per-request store lock |
| `db.py` | 1,374 B | In-memory dict store, logical clock default `2026-05-01T00:00:00Z`; **zero seeding** |
| `errors.py`, `respond.py`, `authz.py` | ~4 KB | Error catalog, envelope (`meta`/`response_type`/`data`, error `error_id`/`message`), header auth + RBAC + coordinator ownership |
| `timeutil.py` | 2,774 B | ISO-8601 parse/format (3-fraction-digit `Z`), date/month math |
| `calc.py` | 8,707 B | All 7 calculation rules with Decimal round-half-up at pinned steps |
| `store_ops.py`, `serialize.py`, `cascades.py` | ~16 KB | Body validation, pagination (`limit`/`offset`/`total_count`/`has_more`), serializers, cascade/ledger cores |
| `routes/` (14 files) | ~62 KB | One blueprint per resource group |

## Verification results
- **Compile**: all 25 Python files pass `py_compile`.
- **Route coverage**: programmatic diff of Flask's `url_map` vs SCAFFOLD.yaml `endpoints` — **80/80 (method, path) pairs, 0 missing, 0 extra** (Flask's built-in `/static` route disabled for exactness).
- **Boot check**: three separate fresh-process boots via `PORT=<port> bash start.sh`; unauthenticated request returns the correct 401 `ERR_UNAUTHENTICATED` envelope; authenticated list returns empty store (`total_count: 0`), confirming no seeding.
- **Behavioral smoke tests** (all passed): full season lifecycle (building release → group confirm → check-in/out → turn task spawn/pass → close-out → finalize → pay → CLOSED → allocation run); minor surcharge + weekend premium pricing (verified exact 32,650-cent provisional total); turn-window reject + 24h-equality pass; supersede atomicity rollback; capacity and participant double-booking; key late-fee grace/cap boundary (0/1500/7500) and pool accounting; cancellation 20%-tier fee + invoice VOID; no-show strict `>checkin+24h`; chaperone ratio 422; screening appeal loop (FLAG→APPEALED→CLEARED); `ERR_REVISION_SUPERSEDED` on stale cancel; damage estimate (7,002) vs assessed pinned-rounding (6,102) with dispute/adjusted-resolve; maintenance window blocked-interval computation and room OUT_OF_SERVICE cascade.

## PRD interpretation decisions (ambiguities)
1. **`SCREENING_VALIDITY_MONTHS`** — referenced in both PRD §3.3 and the scaffold entity table but **no numeric value is declared anywhere**; implemented as **6 months** (flagged in `calc.py`).
2. **Building `version` bumps** — scaffold side-effects state `Building.version += 1` once per endpoint call, so ledger-counter mutations bump once per API call (not once per assignment in multi-assignment cascades).
3. **`ERR_REVISION_SUPERSEDED` precedence** — for `POST /stay-assignments/{id}/cancel` the superseded check runs before the generic `ERR_INVALID_STATE` check, per the PRD §3.5 sentence explicitly rejecting cancellation of superseded revisions' assignments with `ERR_REVISION_SUPERSEDED` (overrides raw priority numbering 8 < 15).
4. **Damage state errors** — `ERR_DAMAGE_NOT_ASSESSED` is treated as the domain-named state error for the four damage ops (assessment's own state), while the parent-group gate on `bill` (IN_HOUSE/DEPARTED) returns `ERR_INVALID_STATE`, matching the scaffold precondition annotations.
5. **Binding intervals for overlap/capacity/turn checks** — RESERVED/CHECKED_IN bind planned intervals, CHECKED_OUT binds actual intervals, CANCELLED/NO_SHOW bind nothing (per the turn-window `input_set`, applied consistently to all three checks).
6. **Duplicate `room_number`/`credential_code` uniqueness** — "unique per building" has no dedicated error ID in the catalog; enforced as `ERR_INVALID_REQUEST` (400).
7. **Payment on a PROVISIONAL invoice** — PRD names `ERR_INVOICE_ALREADY_PAID` only for PAID/VOID; PROVISIONAL returns `ERR_INVALID_STATE` (409).
8. **Pagination out-of-range values** — clamped to declared bounds (limit [1,100], offset ≥ 0); non-integer values rejected with `ERR_INVALID_REQUEST`.
9. **`created_at`/`updated_at`** read from the logical clock (deterministic, per PRD §2.5's "all time-dependent behavior"), while `meta.api_request_timestamp` uses wall-clock UTC as a request-receipt stamp.

## Step 7: Run Tests and Iterate — 2026-08-12T03:03:00.000Z

All 8 rounds pass: **86/86 in every round** (88 original tests minus 2 deleted). Orchestrator independently verified all 8 `results.${i}.json` files on disk: passed=86, failed=0, errors=0, total=86 in each.

## Summary

**Iterations run:** 3 sweeps (sweep 1: 76 real failures hidden by OOM-killed pytest processes; sweep 2: 5 consistent failures after fixture fix; sweep 3: 84/86 with 2 infrastructure restart-timeout errors per round; sweep 4: clean 8×86/86).

**Tests deleted (2):**
- `test_09_validation_order_and_finalize.py::TestStateBeatsTemporal::test_state_beats_temporal_on_cancelled_group_revision` — PRD silence: no sentence in PRD §3.4 or the §4 endpoint table gates rooming-list-revision creation on the parent group's state; the rule exists only in SCAFFOLD_DIFFICULTY_DESIGN's narrative citing a generic "priority 8" state check that the scaffold's own validation list does not apply to this endpoint. Unique-derivability collapse: a faithful PRD-only implementation (like ours) allows revision creation on a CANCELLED group.
- `test_09_validation_order_and_finalize.py::TestStateBeatsTemporal::test_state_error_surfaces_alone_when_temporal_clean` — same instance, same silence (clean-payload leg of the pair).

**Fixes to `test_helpers/`:**
- `fixtures.py` — `create_building_turn_active` / `create_building_released`: the `rooms` parameter was shadowed by `rooms = {}`, so the room-creation loop iterated an empty dict and no rooms were ever created; confirm-release then correctly rejected with ERR_INVALID_STATE (75 tests shared this setup failure). Renamed the local to `room_map`.
- `assertions.py` — added `assert_instant_equal`, comparing clock-stamped timestamps by parsed instant rather than exact string.

**Fixes to `test_suite/`:**
- `test_01_building_season_lifecycle.py::test_list_groups_pagination_envelope` — asserted `len(data) == 2` for `limit=2&offset=2` over 3 rows; PRD defines offset as items *skipped*, so the derivable result is 1. Corrected the assertion.
- `test_05_guest_stays.py` (3 assertions) and `test_11_keys_and_linen.py` (1 assertion) — replaced exact-string timestamp equality (`"2026-06-15T16:00:00Z"`) with `assert_instant_equal`. PRD pins three fractional digits only for `api_request_timestamp`/`created_at`/`updated_at`; the string format of clock-stamped domain fields (`actual_checkin_at`, `window_start`, `window_end`, `returned_at`) is not specified, so exact-string equality is not uniquely derivable. The PRD-covered assertion (stamped instant == clock value) is preserved.

**Fixes to `implementation/`:**
- `start.sh` — replaced the per-boot `python3 -c "import flask"` dependency probe (an extra interpreter spawn on each of ~688 boots per sweep) with a `.deps_installed` sentinel file, eliminating the restart-poll timeouts (15s window) observed under 8-way lockstep boot storms on this shared host. No application behavior changed; no entity data is persisted (sentinel is an empty boot marker sanctioned by INSTRUCTION.md's dependency-install contract).

No implementation logic changes were needed — the API implementation was already PRD-faithful; all functional failures traced to the test artifact.

## Step 8: Finalize PRD — 2026-08-12T03:05:00.000Z

All verification is complete. The final deliverable stands: `PRD_FINALIZED.md` is byte-identical to `PRD.md` — the minimal correct patch is the identity patch, because every Step 7 item traced either to test artifacts or to PRD silence that must be preserved, never to a PRD claim contradicting the implementation.

## Summary

**Line counts / delta:** PRD.md = 313 lines; PRD_FINALIZED.md = 313 lines; 0% delta (diff confirms identical). File produced at `/home/ubuntu/github/CodingPRD/tasks/task_1221_summer_conference_housing_campus_turn/workspace/PRD_FINALIZED.md`.

**Changes:** None. Zero edits survived verification against `implementation/`. Per-item dispositions:

- §3.4 / §2.7 / §4 (deleted `TestStateBeatsTemporal` pair) — **no edit** — PRD contains no wording gating rooming-list-revision creation on parent-group state (checked §2.6 ordering clause, §2.7 OCC clause, §3.4 workflow, §4 endpoint row); instruction (a) mandates leaving silence silent rather than adding a gate.
- §2.3 (pagination test fix) — **no edit** — offset-as-items-skipped was already PRD-pinned verbatim ("The `offset` parameter sets the number of items skipped"); the test assertion was wrong, not the PRD.
- §2.2/§2.4 vs. clock-stamped domain fields (test_05 ×3, test_11 ×1) — **no edit** — PRD pins three fractional digits only for `api_request_timestamp` (§2.2, line 41) and `created_at`/`updated_at` (§2.4, line 76); no sentence implies a string format for `actual_checkin_at`/`window_start`/`window_end`/`returned_at`/etc., so there was no format claim to soften, and adding one would re-introduce the over-specification Step 7 removed.
- `test_helpers/fixtures.py` room-map shadowing — **no edit** — pure test-fixture bug, no PRD subject.
- `implementation/start.sh` `.deps_installed` sentinel — **no edit** — boot/dependency-install mechanics governed by INSTRUCTION.md, outside PRD scope.

**Per-edit pre-edit search log (each candidate edit evaluated, per the mandatory enumeration discipline):**

1. (a) Subject: group-state preconditions on `POST /conference-groups/{id}/rooming-list-revisions`. (b) Paths enumerated: `implementation/routes/groups.py:217-316` (`create_revision` — full read: role check → ownership → 404 → body/FK validation → OCC `expected != g["version"]` → supersede → per-assignment gauntlet; no `g["status"]` rejection anywhere; the only status read is line 306's CONFIRMED-conditional invoice recompute, which PRD §3.4 line 136 already describes); `implementation/calc.py` (`active_revision`, used by confirm/supersede — no state gate); confirmed no other route creates revisions. PRD-side enumeration: §2.6 (generic ordering, explicitly defers per-operation sequences to §3), §2.7 (OCC only), §3.4 (gauntlet only), §4 line 219 (OCC-guarded only). (c) No wording committed — PRD is silent; per instruction (a) silence is preserved (no gate added, no "not gated" clause invented).
2. (a) Subject: pagination offset semantics. (b) Paths enumerated: `implementation/store_ops.py:112-140` (`paginate` — `items[offset:offset+limit]`, i.e., items-skipped); all 14 list endpoints route through it. (c) No wording committed — PRD §2.3 already uniquely determines the impl behavior; editing risked violating NO-NEW-MISMATCH across all list endpoints.
3. (a) Subject: string format of clock-stamped domain timestamp fields. (b) Paths enumerated: `implementation/timeutil.py:56-74` (`fmt_dt`/`fmt_opt_dt`/`fmt_temporal`), every serializer callsite in `implementation/serialize.py` (`superseded_at` L89, `actual_checkin_at`/`actual_checkout_at` L103-104, `decided_at` L117, `window_start`/`window_end` L130-131, `returned_at` L162, `assessed_at` L178, `finalized_at`/`paid_at` L199-200), `implementation/routes/clock.py:19` (`current_utc`), `implementation/respond.py:13` (`api_request_timestamp`); PRD-side grep of "ISO 8601"/"fractional"/"timestamp" (lines 29, 41, 54, 72, 76, 80) plus every "stamped from the clock" site (§3.3-§3.9). (c) No wording committed — impl emits `.mmmZ` uniformly, but PRD never implies a format for domain fields; the aligned contract Step 7 kept is instant-equality ("stamped from the clock"), which the PRD already pins. Pinning a format would exceed what the weakened tests sanction.
4. (a) Subject: dependency-probe/sentinel boot behavior. (b) Paths enumerated: `implementation/start.sh`, `workspace/INSTRUCTION.md` (dependency-install contract). (c) No wording committed — infrastructure, not API behavior.

## Step 9: Complete PRD — 2026-08-12T03:24:00.000Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1221_summer_conference_housing_campus_turn/workspace/PRD_COMPLETED.md`.

**Size:** PRD_FINALIZED.md 313 lines / 57,811 chars → PRD_COMPLETED.md 313 lines / 61,914 chars; char-delta +4,102 (17 paragraphs edited in place; no lines or sections added).

**Counts:** 22 ambiguity-pins, 1 mismatch-revision (23 logical changes across the 17 edited paragraphs).

**Changes (one bullet each):**

- §2.3 — insert — ambiguity — out-of-range `limit` clamped into [1,100], negative `offset` clamped to 0, non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` — implementation/store_ops.py:112-140
- §2.3 — revise — ambiguity — list ordering pinned to creation (persistence) order, which equals `created_at` ascending only when the logical clock is not moved backward (impl sorts by insertion sequence) — implementation/store_ops.py:143-144
- §2.3 — insert — ambiguity — every list endpoint whose resource has a `status` field also accepts an optional `status` filter (buildings, rooms, groups, revisions, screenings, turn-tasks, maintenance windows, allocation runs) — implementation/routes/buildings.py:55-57, rooms.py:28, groups.py:78,324, screenings.py:52, maintenance.py:64, allocations.py:63
- §2.4 — revise — ambiguity — `version` starts at 1; `created_at`/`updated_at` are stamped from the logical clock, never wall-clock — implementation/store_ops.py:17-24
- §2.5 — insert — ambiguity — comparisons of date-valued fields (arrival/departure, window start/end, allocation period) are by calendar date; datetimes are first reduced to their UTC date — implementation/timeutil.py:48-53, routes/groups.py:51, routes/maintenance.py:39-42, routes/allocations.py:28
- §2.6 — insert — ambiguity — the escalation and coordinator-ownership checks that require the addressed child resource (turn task, stay assignment, screening, damage assessment) run after that path id resolves, so a missing resource yields `ERR_NOT_FOUND` first — implementation/routes/turns.py:54-59, stays.py:106-109, screenings.py:98-99, damage.py:78-79
- §2.6 — insert — ambiguity — typed-body-field rule: integers for counts/cents/versions, booleans for flags, stated minimums enforced; violations → `ERR_INVALID_REQUEST` — implementation/store_ops.py:54-96
- §2.6 — insert — ambiguity — `ERR_DATE_RANGE_INVALID` runs as a temporal business rule after the OCC check, so on maintenance-window creation a stale building version surfaces before an invalid range — implementation/routes/maintenance.py:36-42
- §2.6 — insert — ambiguity — blanket pin: any §3 state restriction or "permitted only" guard without a named domain error rejects with `ERR_INVALID_STATE` (covers fall-prep/certify guards, confirm-release room minimum, submit participant minimum, add-participant states, linen issue states, damage-bill group gate, allocation lock, etc.) — invalid_state usages across routes/
- §2.8 — revise — mismatch — PRD read as each ledger-counter adjustment incrementing the building's `version`; pinned to one increment per API call regardless of how many counter adjustments the call makes — implementation/cascades.py:1-6, routes/groups.py:301-302,460-461
- §3.1 — revise — ambiguity — duplicate `room_number` within a building → `ERR_INVALID_REQUEST` — implementation/routes/buildings.py:172-175
- §3.2 — revise — ambiguity — deposit `amount_cents` is an integer ≥ 0 and deposits are accepted in any group status — implementation/routes/groups.py:94-102
- §3.3 — revise — ambiguity — `SCREENING_VALIDITY_MONTHS` pinned to 6; month arithmetic clamps day-of-month to the target month's last day — implementation/calc.py:45-48, timeutil.py:77-82
- §3.3 — revise — ambiguity — the freshness gate rejects only when *all* of a participant's `CLEARED` screenings are expired; one unexpired clearance satisfies it — implementation/routes/groups.py:381-388
- §3.3 — revise — ambiguity — `decided_at` is stamped on every decide/resolve-appeal outcome, including `FLAG` and `DENY` — implementation/routes/screenings.py:85-91,118-124
- §3.4 — insert — ambiguity — revision payload FK rules (`room_id` must exist, `participant_id` must belong to the group, else `ERR_INVALID_REQUEST`), empty `assignments` array permitted, revisions creatable in any group status — implementation/routes/groups.py:224-245
- §3.4 — insert — ambiguity — per-assignment date-range check (`ERR_DATE_RANGE_INVALID`) positioned immediately after the room-reservability check and before double-booking — implementation/routes/groups.py:157-168
- §3.7 — revise — ambiguity — linen `loss_charge_cents` is set by the same rule at issuance (a fresh issue charges every issued pack as unaccounted), not only on returns — implementation/routes/linen.py:37-40
- §3.7 — revise — ambiguity — key issuance: `participant_id` must belong to the group and duplicate `credential_code` in the building both reject with `ERR_INVALID_REQUEST`; issuance permitted in any group status — implementation/routes/keys.py:27-40
- §3.8 — insert — ambiguity — damage line-item validation: `description` string, `quantity`/`unit_replacement_cost_cents`/`fixture_age_months` non-negative integers, at report time and for `adjusted_line_items` at resolve alike, else `ERR_INVALID_REQUEST` — implementation/routes/rooms.py:36-58, damage.py:99-101
- §3.9 — revise — ambiguity — bed-night ordering ties at equal participant `created_at` (same logical instant) are broken by creation sequence — implementation/calc.py:78-97
- §3.9 — revise — ambiguity — finalize requires the invoice still `PROVISIONAL`; an invoice no longer `PROVISIONAL` (e.g. already `FINALIZED`) → `ERR_INVOICE_NOT_FINALIZABLE` — implementation/routes/invoices.py:42-44
- §3.9 — revise — ambiguity — payment against a `PROVISIONAL` invoice → `ERR_INVALID_STATE` (only `PAID`/`VOID` raise `ERR_INVOICE_ALREADY_PAID`) — implementation/routes/invoices.py:75-79

Everything else in the impl (check-in check order, no-show 24h strictness, cancellation tiers, turn-task spawn/cascade rules, damage depreciation and dispute window, waterfall order, OCC endpoints, error catalogue statuses, role lists, revision immutability) was verified already uniquely pinned by the PRD and left untouched.
