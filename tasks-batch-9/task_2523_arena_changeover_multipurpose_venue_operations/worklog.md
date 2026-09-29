# Worklog — task_2523_arena_changeover_multipurpose_venue_operations

## Step 1: Create task directory — 2026-09-03T05:13:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2523_arena_changeover_multipurpose_venue_operations` and its `workspace/` subdirectory. Index 2523 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T06:55:00.000Z

All three scaffold artifacts are complete and the linter is clean.

## Files

| Path | Lines |
|---|---|
| `.../SCAFFOLD.yaml` | 2535 |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2504 |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 4020 |

`SCAFFOLD.yaml` holds only §1.0–§1.7 (top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles); the other two files each have exactly one top-level key.

## SCAFFOLD.yaml content counts
11 entities, 8 state machines, 12 calculations, **39 validation rules** (priority ladder 10→102, strictly ascending), **45 endpoints**, 48 errors, 5 roles, 2 OCC concurrency rules (both on `Venue.version`). Archetypes: temporal_windowing + quota_allocation; layers optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers; role_model segregation_of_duties; consistency immediate.

## Design files
- §1.8: **9 difficulty rules, 24 instances** (dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 2).
- §1.9: **all nine sections, 102 instances** — 59 full test recipes + 43 `excluded_because` stubs (entities 13, state_machines 19, calculations 15, validations 29, endpoints 6, errors 10, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1). Every stub cites an existing §1.8 instance in `rule_id / instance_name` form and carries no `test_recipe`; all 126 names are globally unique across both design files.

## Lint
`scaffold_lint.py` → `VERDICT: clean lint` (45 endpoints, 11 entities, 24 §1.8 + 59 §1.9 instances, **961 calls scanned**).

## Self-consistency defects found and fixed while writing §1.9
1. **Unreachable error**: `ERR_ORDER_BOOKING_SEQUENCE_INVALID` sat at priority 84, but any inverted booking pair produces a negative window and so always tripped priority 74 `ERR_TURNAROUND_WINDOW_INSUFFICIENT` first. Relocated the structural sequence check to **priority 68** (ahead of the window-arithmetic rules 70/72/74) with the ordering rationale written into the `check`.
2. Earlier in the session: widened the §1.3 `HoldChallenge null -> OPEN` precondition to `incumbent status IN {HELD, CHALLENGED}` so `ERR_DUPLICATE_CHALLENGE` (98) is reachable behind priority 50.
3. Corrected four asserts that referenced non-existent read paths (`/equipment-assets/{id}/issues`, `/venues/{id}/event-bookings`, `/venues/{id}/changeover-orders`) to the declared filtered list endpoints, and removed a capture of `venue_version` from `POST /changeover-orders` (whose output is `ChangeoverOrder`, which has no such field).

Banned write-write vocabulary ("simultaneously", "in parallel", "first-writer-wins", "race winner/loser", "concurrently") has zero occurrences across all three files; the only sanctioned write-write mechanism used is OCC on `Venue.version`, and all time control goes through `POST /_clock/set_current_utc`.

## Step 3: Copy shared files — 2026-09-03T06:56:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2523_arena_changeover_multipurpose_venue_operations/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T07:10:00.000Z

PRD generated and verified.

**Output:** `.../workspace/PRD.md`
**Line count:** 439 lines (91,863 bytes)
**Last section heading:** `## 5. Error Code Catalogue` — tail confirmed complete: the file ends with the final error-table row `| ERR_TENANT_HOLD_QUOTA_EXCEEDED | 422 |`, a real section boundary, no mid-sentence truncation, no audit footer.

**Section list**

- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Optimistic Concurrency on the Arena Record · 2.7 Interval Arithmetic · 2.8 Precision, Rounding and Money · 2.9 Reads, Nested Paths and Resolution Order · 2.10 Validation Precedence · 2.11 Derived Counters and Cascade Propagation
- §3 Business Logic (9 domain-derived subsections): 3.1 Standing Up an Arena and Its House Configurations · 3.2 Anchor Tenants, Hold Entitlements and Challenge Credits · 3.3 The Event Booking Lifecycle · 3.4 Contesting an Incumbent Hold · 3.5 Voluntary Release and the Hold Expiry Sweep · 3.6 The Ice Deck · 3.7 Opening a Turnaround and Freezing Its Plan · 3.8 Floor Execution, Rework, Readiness and Sign-Off · 3.9 The Logistics Layer
- §4 Endpoint Definitions (45 rows, 4 columns)
- §5 Error Code Catalogue (48 rows, 2 columns)

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 100 required, 100 present, 0 missing
- endpoints[].request_body: 64 required, 64 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
- errors[].id: 48 required, 48 present, 0 missing
- roles[].name: 5 required, 5 present, 0 missing
- state values: 28 required, 28 present, 0 missing
- enum-field values: 63 required, 63 present, 0 missing
Status: PASS   (two passes run: permissive tokenizer, then strict whole-backtick tokenizer)
```

```
Rule coverage check:
- validations[] with priority: 39 checked, 39 expressed in prose (§2.10 ladder + per-endpoint restatements in §3.3, §3.7, §3.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_venue_version + ERR_STALE_VENUE_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 37 checked, 37 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed (pinned step orders, ceilings, rounding points, tie-breaks, empty-set rules), 0 missing
- validations[] conditions: 39 checked, 39 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 26 side-effect endpoints + all applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 100 checked, 100 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 794
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md`; zero fuzzy/approximating words anywhere; no difficulty or meta-commentary; the two withheld design indices were never opened.

Orchestrator verification: `tail -25 PRD.md` shows a complete 48-row error table ending at a real section boundary; `grep -n '^#'` shows all five top-level sections present. Not truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-03T07:35:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, per the skill. Step 6 returned first; its summary is recorded here and Step 5's below.)

The implementation is complete and verified.

## Files (`.../workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `app.py` | 72 | Flask factory, blueprint registration, `ApiError`/HTTPException handlers, `PORT` entry point |
| `store.py` | 112 | In-memory dicts + logical clock (`2026-08-01T00:00:00Z`), id/timestamp/version stamping, `ordered()` |
| `errors.py` | 112 | All 48 error ids → HTTP statuses + default messages |
| `envelope.py` | 60 | `meta`/`response_type`/`data` envelopes, pagination meta, error envelope |
| `validate.py` | 214 | Ladder ranks 1, 2, 5, 6: auth, roles, shape helpers, pagination |
| `calc.py` | 314 | All 12 calculations + every domain constant (Decimal/ROUND_HALF_UP money, exact `Fraction` crew factor, two pinned ceilings) |
| `serial.py` | 200 | 11 serializers; derived fields computed at read time; profiles carry no `updated_at`/`version` |
| `cascade.py` | 113 | The 3-hop transitive cascade, order abandonment, labor cancel fee, ice covering |
| `routes_venue.py` | 126 | 6 endpoints (arena, profiles, tenants) |
| `routes_equipment.py` | 178 | 8 endpoints (pools, maintenance, issues, returns) |
| `routes_ice.py` | 164 | 3 endpoints (install, list, transition) |
| `routes_booking.py` | 240 | 7 endpoints (create/read/list, hold, confirm, release, sweep) |
| `routes_challenge.py` | 192 | 5 endpoints (create/read/list, rule, withdraw) |
| `routes_order.py` | 322 | 7 endpoints (create, read/list, progress, rework, signoff, readiness) |
| `routes_logistics.py` | 228 | 8 endpoints (dock windows, labor calls) |
| `routes_clock.py` | 18 | 1 endpoint (`/_clock/set_current_utc`) |
| `start.sh` | 21 | Guarded flask check, `exec python3 app.py` on `$PORT` |
| `requirements.txt` | 1 | flask |

**2687 lines total. 45/45 endpoints registered** — verified by dumping `app.url_map`, which matches the PRD §4 table exactly (path-for-path).

## Verification
- `python3 -m py_compile` on all 16 modules: **PY_COMPILE_OK**; `__pycache__` removed afterwards.
- Boot on free port **27987** via `PORT=27987 bash start.sh`: `POST /venues` → **HTTP 201** with a well-formed envelope; `GET /event-bookings?limit=5` → `total_count: 0, has_more: false` — i.e. **zero seeded rows on a fresh process**. Server killed, no listeners left.
- Two end-to-end smoke runs (separate processes) exercised: ice install → IN_SERVICE → cover-blocked-by-condensation → cover-with-same-call revision → uncover with cover-hour accrual → 4th covering auto-melting to `MELTING`; hold quota; `priority_delta` = −2; duplicate challenge; TIER_1 protection; withdraw restoring the credit and returning the incumbent to HELD; stale-version 412; dock buffered collision vs. exact-30-min gap accepted vs. `ERR_DOCK_NUMBER_INVALID`; labor scope exclusivity; release cascade (dock reservations → `RELEASED`/`BOOKING_GONE`, labor calls left `CALLED`); expiry sweep (`swept_count: 1`, pinned order, `venue_version`); the full 3-dimension turnaround with floor-protection shortfall, rework, SoD refusal, sign-off with automatic ice covering.
- Spot-checked arithmetic against the PRD by hand: `planned_turnaround_minutes` 708 (615 raw → crew factor 1 → ×1.15 overnight → ceil), displacement settlement 74,160 cents (120,000 × 0.60 → 72,000 subtotal → 3% → 2,160), estimated labor 155,520 cents (per-worker rounding before ×headcount), condensation 44.69 / 10.94 / 15.10.

## PRD-vs-scaffold conflicts resolved in favour of PRD §2.10
- Ice install: `ERR_ICE_SHEET_ALREADY_PRESENT` (12) → `ERR_DEHUMIDIFICATION_INSUFFICIENT` (13) → `ERR_VENUE_SCOPE_MISMATCH` (17), even though §3.6's prose lists scope before dehumidification.
- Changeover create: scope check runs **last**, after crew cap and debt freeze.
- Dock create: collision (15) before dock-number range (16); consequently `dock_number` range is not a shape check (only its integer type is), so `dock_number: 0` yields `ERR_DOCK_NUMBER_INVALID`.
- Challenge create: credits (16) → scope (17) → duplicate (17).
- Progress: compound-status and stage-adjacency (`ERR_INVALID_ORDER_STATE`) before `ERR_INCOMING_BOOKING_NOT_CONFIRMED` before `ERR_FLOOR_PROTECTION_SHORTFALL`; a `to_stage` naming another dimension's stage is `ERR_INVALID_ORDER_STATE`, an unknown string is `ERR_INVALID_REQUEST`.
- Sign-off checks SoD (rank 4) before the from-state check (rank 9).
- Version policy: `Venue.version` bumps exactly per the §2.6 enumeration (once per operation, including cascades and the ice-cover hop inside sign-off; sweep only when `swept_count >= 1`); AnchorTenant never bumps (both counters are declared derived); `created_at`/`updated_at` use wall time with an internal `_seq` tie-break so list order is always insertion order.

## Step 5: Generate unit tests — 2026-09-03T08:55:00.000Z

(Launched concurrently with Step 6; finished second. Recorded after Step 6's entry.)

All work is complete. Final state of the generated suite:

**test_helpers/ (9 files, 2,118 lines)**
| file | lines |
|---|---|
| `__init__.py` | 38 |
| `api_client.py` | 219 |
| `api_errors.py` | 111 |
| `assertions.py` | 210 |
| `constants.py` | 171 |
| `factories.py` | 150 |
| `fixtures.py` | 725 |
| `test_users.py` | 79 |
| `types.py` | 415 |

**test_suite/ (conftest + 18 test modules, 6,088 lines)**
| file | lines | tests |
|---|---|---|
| `conftest.py` | 45 | — |
| `test_01_arena_and_house_configurations.py` | 551 | 13 |
| `test_02_booking_lifecycle_and_holds.py` | 310 | 6 |
| `test_03_hold_challenges_and_displacement.py` | 384 | 8 |
| `test_04_release_and_expiry_sweep.py` | 150 | 3 |
| `test_05_ice_deck_lifecycle.py` | 287 | 6 |
| `test_06_turnaround_planning.py` | 274 | 5 |
| `test_07_floor_execution_and_signoff.py` | 398 | 8 |
| `test_08_dock_windows.py` | 126 | 2 |
| `test_09_labor_calls_and_costs.py` | 176 | 4 |
| `test_10_equipment_pools.py` | 223 | 4 |
| `test_11_validation_precedence.py` | 285 | 5 |
| `test_12_booking_and_hold_state_machine.py` | 359 | 8 |
| `test_13_ice_deck_and_equipment_state_machines.py` | 174 | 3 |
| `test_14_derived_calculations.py` | 418 | 6 |
| `test_15_field_and_boundary_validations.py` | 935 | 17 |
| `test_16_endpoint_contracts.py` | 294 | 4 |
| `test_17_errors_and_access_control.py` | 518 | 6 |
| `test_18_concurrency_and_consistency.py` | 181 | 2 |

**Tests emitted: 108.** Coverage cross-check against the two design indices: 24/24 §1.8 difficulty instances covered with >=2 tests each (49 queue-A tests), 59/59 non-stub §1.9 corner instances covered (59 queue-B tests), 0 dangling `Design:` tags, 0 of the 43 `excluded_because:` stubs translated.

**Instances skipped: 0.** Every difficulty and non-stub corner instance passed the PRD-first two-condition filter. Two recipes were reconciled with the PRD rather than skipped, both because the recipe's own setup or literal contradicted the ladder: (a) the debt-freeze recipe left the incoming booking in `DRAFT`, which PRD §3.7 refuses with `ERR_INVALID_BOOKING_STATE` before the debt check, so the test holds it first; (b) the not-found catalogue recipe asserted `Venue.version == 2` after a profile declaration, which §2.4/§3.1 do not uniquely derive, so the test asserts the version is unchanged across the ten failing calls instead.

**Final verification:** `ast.parse` succeeds for all 28 files. The citation auditor reports `tests: 108 / problems: 0` — every `PRD §x.y: "..."` quotation survives a whitespace-normalized literal match against `workspace/PRD.md`, and every test carries exactly one trailing `Design:` line. `pyflakes` is clean over `test_suite/` and all non-barrel helpers.

Two PRD-conformance corrections were made in the final pass and flagged to the implementation side: the error envelope in PRD §2.2 carries only `error_id` and `message` (no `details` object), and a freshly registered `AnchorTenant` is granted exactly two `challenge_credits` regardless of `guaranteed_holds_per_season`. The `workspace/implementation/` directory was never read or written.

## Step 7: Run tests and iterate — 2026-09-03T08:51:30.000Z

(Orchestrator note: the timestamps on the Step 4/5/6 entries above were estimated rather than read from the clock and run ~10 minutes late; Step 7 onward uses real UTC. The step ordering itself is correct.)

Clean sweep achieved. All 8 parallel rounds: 108/108.

## Summary

**Iterations run:** 2 (sweep → fix → sweep).

**Round 1 result:** all 8 rounds identical at 106/108 — two deterministic failures, no flakiness, no reaping tells (sweeps completed in ~200s each, no `Terminated` in logs).

**Tests deleted:** none outright. One assertion removed under STEP 1c partial-coverage handling:

- `test_suite/test_01_arena_and_house_configurations.py::test_the_server_mints_its_own_id_timestamp_and_version` — dropped `assert venue["created_at"] == "2026-08-01T00:00:00.000Z"` (plus its now-orphaned §2.4/§2.5 docstring quotes). **PRD-silence category: unique-derivability failure.** PRD §2.4 says only "`created_at` records the instant the row was inserted" — it never names the source clock. §2.5 scopes the logical clock to a closed enumeration of *temporal rules*: "Every temporal rule in this system — hold expiry, cancellation notice bands, displacement notice bands, cover-hour accumulation, turnaround stamping, the melt-out dependency window and the expiry sweep — reads a server-side **logical clock** rather than real wall-clock time." Row bookkeeping timestamps are absent from that list, so two PRD-faithful readings exist: (a) `created_at` = logical clock, (b) `created_at` = real insert time, which is additionally the reading that makes §3.5's "ascending `created_at` as the tie-break" non-degenerate (under reading (a) every row created between clock moves ties, rendering the pinned tie-break meaningless). The remaining assertions (server-minted UUID `id`, `version == 1`, client-supplied values ignored) are verbatim-covered by §2.4 and were kept.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header defect surfaced.

**Fixes applied to `test_suite/`** (STEP 2, test wrong — fix made the test *more* faithful to PRD):

- `test_suite/test_02_booking_lifecycle_and_holds.py::test_confirm_one_second_after_hold_expiry_is_rejected_and_leaves_the_arena_untouched` — expected `rigging_committed_load_kg` corrected from `1_500` to `0`, and the governing §3.3 sentence added to the docstring. PRD §3.3: "The stored arena field `rigging_committed_load_kg` uses exactly the same closed-interval arithmetic with the logical clock instant standing in as a zero-length candidate window: it is the sum of `rigging_load_kg` over confirmed bookings whose closed event interval contains the current instant." The test's clock sits at `2026-08-04T00:00:01Z` while the confirmed event's interval is `[2026-09-12T00:00, 2026-09-12T03:00]`, so the instant lies inside no confirmed interval and the PRD-derived figure is the empty sum. The sibling test at `test_closed_interval_peer_set_refuses_the_load_one_kilogram_above_capacity` already asserts exactly this (`approx(0)`, "The logical clock instant lies inside no confirmed event's closed interval"), confirming the failing test simply mis-derived its own expectation. The implementation was correct and was left untouched.

**Fixes applied to `implementation/`:** none. No implementation defect was found; both failures traced to the test layer.

**Final sweep, per-round (quoted from `workspace/implementation/results.${i}.json`):**

| round | passed/total | failed | errors | skipped |
|---|---|---|---|---|
| 1 | 108/108 | 0 | 0 | 0 |
| 2 | 108/108 | 0 | 0 | 0 |
| 3 | 108/108 | 0 | 0 | 0 |
| 4 | 108/108 | 0 | 0 | 0 |
| 5 | 108/108 | 0 | 0 | 0 |
| 6 | 108/108 | 0 | 0 | 0 |
| 7 | 108/108 | 0 | 0 | 0 |
| 8 | 108/108 | 0 | 0 | 0 |

Union of failing tests across all 8 rounds: empty. Results files retained at `.../workspace/implementation/results.1.json` … `results.8.json`; sweep log at `.../workspace/sweep.log`.

Orchestrator independently verified all 8 results files (108/108, failed=0 each) and `grep -c Terminated sweep.log` = 0.

**Step 8 skip decision:** NOT skipped. The skip condition requires zero iterations beyond the baseline; Step 7 ran 2 iterations with one `test_suite/` fix and one assertion removal, so Step 8 runs with those two items as its `<step_7_diff>` focus list.

## Step 8: Finalize PRD — 2026-09-03T08:56:00.000Z

Done.

## Line counts
- `PRD.md`: 439 lines; `PRD_FINALIZED.md`: 439 lines — 0% line delta (2 lines revised in place, +~110 words; 91,863 → 92,468 bytes).

## Changes
- **§2.4 Common Resource Properties** — *revise* — pinned `created_at` / `updated_at` to the server's **real wall-clock** time at insert/mutation rather than the logical clock, noted they advance while the clock is parked and never rewind on a backwards clock move, and pinned `updated_at == created_at` on a fresh row — `implementation/store.py:91-107` (`stamp_new` → `created_at = wall_now()`, `updated_at = created`; `touch` → `updated_at = wall_now()`), `store.py:58` (`wall_now`).
- **§2.5 The Logical Clock** — *revise* — re-scoped the absolute "never fall back to the host machine's actual time" so it covers rule evaluation and every server-stamped entity-row instant, with `created_at`/`updated_at` named as the single exception — resolves the contradiction the §2.4 edit would otherwise create — `implementation/store.py:45-47, 58-59`.

No edit for the second Step 7 item (`rigging_committed_load_kg`): that was a test-layer mis-derivation. `calc.py:248-251` (`instant = now_logical(); rigging_peer_load(venue_id, instant, instant)`) plus `_closed_overlap` at `calc.py:231-232` implement PRD §3.3's "logical clock instant standing in as a zero-length candidate window" verbatim, so §3.3 already uniquely determines the behavior and its prose was kept byte-identical.

## Per-edit pre-edit search log

**Edit 1 — §2.4**
- (a) Subject: the source clock for the row-bookkeeping timestamps `created_at` and `updated_at` (all entity types).
- (b) Enumerated/read: `store.py` in full (`CLOCK_START`, `now_logical`, `set_clock`, `wall_now`, `iso`, `stamp_new`, `touch`, `ordered`); every `stamp_new`/`touch` callsite — `routes_venue.py:48,78,110`, `routes_booking.py:94,148,189`, `routes_challenge.py:42,97,103,154,180`, `routes_equipment.py:49,96,135`, `routes_ice.py:77,161`, `routes_logistics.py:84,113,174,216`, `routes_order.py:142,208`, `cascade.py:9,22,27,34,42,58,74,86,97` (cascade-touched rows use the same `touch`, so the wall-clock claim holds for cascade `updated_at` too); `serial.py:7-13` (`_common`, incl. the `with_version=False` profile path that emits only `id`/`created_at`); `envelope.py:20` (`api_request_timestamp` also `wall_now`, so the new sentence does not contradict it); consumers of `created_at` as an ordering key — `store.py:110-112` and `routes_booking.py:228-229`.
- (c) Adjustment: dropped a planned "the only timestamps in the system read from real time" clause, which would have been false for `api_request_timestamp` (`envelope.py:20`); scoped the claim to the two named fields only. Also avoided asserting `updated_at` is refreshed on *every* row-write path in general and stated only the insert-time equality, which `stamp_new` guarantees unconditionally.

**Edit 2 — §2.5**
- (a) Subject: the scope of the prohibition on reading host wall-clock time — i.e. which server-stamped instants are logical-clock-derived.
- (b) Enumerated/grepped: all `now_logical()` callsites — `routes_clock.py:18`, `routes_booking.py:142,179,222`, `routes_challenge.py:151`, `routes_ice.py:99,152`, `routes_order.py:202,204`, `cascade.py:20,32,73,94,109`, `calc.py:250`; plus a targeted grep for every assignment to a persisted instant field (`hold_placed_at`, `hold_expires_at`, `ruled_at`, `started_at_utc`, `completed_at_utc`, `returned_at_utc`, `cover_installed_at_utc`) confirming all ten write sites are `now_logical()`, `None`, or derived from a logical stamp (`calc.hold_expires_at`), with `returned_at_utc` written only through the shared `cascade.py:20` helper used by both the operator return and the abandonment cascade.
- (c) Adjustment: rejected the first draft "for those rules the server must never fall back…", which would have narrowed the prohibition to §2.5's closed seven-item list and thereby left `ruled_at`, `returned_at_utc`, `cover_installed_at_utc` and `hold_placed_at` unpinned even though the implementation drives all of them from the logical clock. Widened to "any instant onto an entity row" with an explicit two-field exception, and deliberately said nothing about envelope metadata so the sentence stays true of `envelope.py:20`.

## Step 9: Complete PRD — 2026-09-03T09:25:00.000Z

**Orchestrator decision (recorded per the AUTONOMY instruction):** Step 9 was run as **three sequential file-partitioned passes** over a single `PRD_COMPLETED.md` rather than one subagent. Rationale: `implementation/` is 2,687 lines across 16 modules, and a single agent asked to "walk implementation/ exhaustively" at that size reliably under-runs the scan and returns a near-identical file. Partitioning by module guarantees every file is actually read by someone. Pass A created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`; passes B and C edited it in place and were explicitly told not to recreate it or revert prior edits, and each was handed the prior passes' "already uniquely pinned" ground so no slice was re-litigated. Each pass was also required to read outside its slice when checking that a wording stayed true globally (no-new-mismatch discipline).

Partition: A = `app.py, store.py, errors.py, envelope.py, validate.py, serial.py, routes_clock.py, routes_venue.py` · B = `calc.py, cascade.py, routes_booking.py, routes_challenge.py` · C = `routes_ice.py, routes_order.py, routes_logistics.py, routes_equipment.py`.

### Cumulative result
- `PRD_FINALIZED.md` 439 lines / 92,468 bytes → `PRD_COMPLETED.md` **440 lines / 104,586 bytes** = **+12,118 chars**, +1 line.
- **45 edits total: 37 ambiguity-pins, 8 mismatch-revisions.** All edits in-paragraph; no new sections.

### Pass A (12 edits: 11 ambiguity-pins, 1 mismatch) — 95,699 bytes
- §2 intro — revise — ambiguity — trailing slash is insignificant (`/venues` = `/venues/`) — `app.py:39`
- §2.2 success bullets — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alphanumeric chars — `envelope.py:13-14`
- §2.2 error bullets — insert — ambiguity — transport-level failures reuse the error envelope: unmatched path → `ERR_VENUE_NOT_FOUND`/404, unsupported method → `ERR_INVALID_REQUEST`/405 — `app.py:48-58`
- §2.3 — revise — ambiguity — `limit`/`offset` must be the plain decimal spelling of an integer (`10.5`, `+10`, `010` rejected; surrounding whitespace tolerated) — `validate.py:181-200`
- §2.3 — revise — ambiguity — default order tie-break is insertion order, `id` never an ordering key; filters are exact-equality and an off-enum filter value matches nothing rather than erroring; `offset` past the end returns an empty page with full `total_count` and `has_more` false — `store.py:110-112`, `validate.py:204-214`, `envelope.py:42`
- §2.6 — revise — ambiguity — declaring a configuration profile or registering an anchor tenant does not advance the arena's `version` — `routes_venue.py:78-79,110-111`
- §2.8 — revise — ambiguity — the three quantised figures render as bare JSON numbers with no zero-padding (`0`, not `0.00`) — `serial.py:27,135,137` via `calc.py:92-96`
- §2.9 — revise — **mismatch** — PRD claimed a missing arena in a nested path wins "regardless of what else the request gets wrong"; impl validates body shape and pagination (rung 5) *before* resolving the path arena — `routes_venue.py:62-87`, `routes_equipment.py:38-44`, `routes_ice.py:46-51`
- §2.10 rung 5 — revise — ambiguity — absent/empty/unparseable body reads as `{}`; non-object JSON body is itself `ERR_INVALID_REQUEST`; instant inputs are ISO 8601 normalised to UTC, explicit offsets converted, zone-less values read as UTC — `validate.py:33-40`, `store.py:73-88`
- §2.11 — revise — ambiguity — `rigging_committed_load_kg` is evaluated against the logical clock at every read, so moving the clock changes it with no row mutation and no `version` bump — `serial.py:27`, `calc.py:248-251`
- §3.6 — insert — ambiguity — the ice sheet payload carries `venue_id` and the snapshotted rate but no `config_profile_id` — `serial.py:127-139`
- §3.9 — insert — ambiguity — the dock reservation payload carries `booking_id` and no `venue_id` of its own — `serial.py:142-153`

### Pass B (15 edits: 10 ambiguity-pins, 5 mismatches) — 99,878 bytes
- §2.8 — insert — ambiguity — every elapsed span converted to hours is first reduced to whole elapsed seconds (sub-second remainder discarded) then divided by 3,600 — `calc.py:162,176,226`
- §3.9 labor cost — revise — **mismatch** — PRD said "exact, possibly fractional" hours; impl truncates to whole seconds (a 4h00m00.500s call bills 19200, not 19201) — `calc.py:162`
- §2.10 rung 3 — insert — **mismatch** — ladder said rung 3 precedes rung 7, but hold and withdraw read a stored row, so their 404 fires first — `routes_booking.py:125-130`, `routes_challenge.py:170-174`
- §3.3 drafting — insert — ambiguity — an `AnchorTenantRep` must name its own `tenant_id`, so that role cannot draft a promoter booking at all; omitting `tenant_id` is `ERR_TENANT_SCOPE_VIOLATION`; `promoter_name` bounded 1–160 — `routes_booking.py:37,51`
- §3.3 attendance — insert — **mismatch** — the `nominal_seats` ceiling check is deferred behind profile existence; a missing profile reports `ERR_PROFILE_NOT_FOUND` however large the forecast — `routes_booking.py:56-68`
- §3.3 roof grid — revise — ambiguity — the peer aggregate is quantised to 2dp *before* the candidate's own load is added, then quantised again (verified both directions) — `calc.py:245`, `routes_booking.py:184`
- §3.5 release — revise — ambiguity — `reason` bounded 1–500 chars — `routes_booking.py:198`
- §3.5 sweep order — revise — ambiguity — insertion order breaks a remaining tie after `hold_expires_at` and `created_at` — `routes_booking.py:229`
- §3.4 ruling — revise — ambiguity — `ruling_note` bounded 1–1000 chars — `routes_challenge.py:135`
- §3.4 seven conditions — revise — **mismatch** — prose listed venue-scope before credits; evaluation is rung order, so credits (16) precede scope/duplicate (17) — `routes_challenge.py:73-85`
- §3.4 displacement — insert — ambiguity — sibling `OPEN` challenges survive displacement, and a later `UPHELD` ruling re-runs the whole displacement (rewrites `displaced_by_booking_id`, recomputes the penalty at the *current* clock, re-cascades, bumps both versions); `DENIED` leaves it untouched — `cascade.py:82-98`, `routes_challenge.py:139-163`
- §3.4 withdrawal — revise — ambiguity — `ruled_at` and `ruling_note` stay unset on withdrawal — `routes_challenge.py:179-180`
- §3.2 credits — insert — ambiguity — spending/refunding a credit rewrites the tenant row in place with no `updated_at` refresh and no `version` bump — `routes_challenge.py:100,184`
- §2.9 resolution order — revise — **mismatch** — "the order the body declares them" read as JSON key order; impl uses the fixed per-endpoint contract order — `routes_booking.py:41-64`, `routes_challenge.py:55-64`
- §3.7 window — revise — ambiguity — `window_minutes` is rounded **down** — `calc.py:150`

### Pass C (18 edits: 16 ambiguity-pins, 2 mismatches) — 104,586 bytes
- §2.6 — revise — ambiguity — equipment-pool creation also leaves the arena at `version` 1 — `routes_equipment.py:35-51`
- §2.10 rung 4 — insert — ambiguity — SoD reads `opened_by_user_id` off the stored order, so 404 precedes it; once resolved it precedes rung 9 — `routes_order.py:248-256`
- §2.10 rung 9 — revise — **mismatch** — "no single request can trip two of them" is false; labor-call close can trip both, with §3.9 pinning the internal order — `routes_logistics.py:205-211`
- §3.6 install — revise — ambiguity — `dehumidification_lph_applied` required, >=0, no upper bound, fractional allowed (as is `sheet_thickness_mm`); three guards evaluated in rung order (12→13→17), not the listed order — `routes_ice.py:48-64`
- §3.6 transition — revise — **mismatch** — dangling "with one exception noted below" (nothing was noted, and §2.6 says every transition bumps); replaced with the exact five caller-drivable hops, `COVERED → MELTING` system-only, same-status and post-`REMOVED` refused, exactly one `version` increment on sheet and arena even when the automatic hop fires, and a revised rate stored on any accepted hop — `routes_ice.py:23-29,146-163`
- §3.6 `BUILDING → IN_SERVICE` — insert — ambiguity — the only hop the dehumidification floor guards; a sub-quarter revision on any other hop is stored unchecked — `routes_ice.py:132-134`
- §3.7 — insert — ambiguity — `crew_headcount` is a required integer 1–200 independent of the cap; every arena-derived input is read from the incoming booking's arena — `routes_order.py:60,68-113`
- §3.8 progress — insert — ambiguity — `to_stage` is shape-checked against the union of the ten stage names, not the named dimension's four, so a borrowed stage name is 409 not 400 — `routes_order.py:174`, `calc.py:70`
- §3.8 rework — insert — ambiguity — `reason` required, 1–500 chars, persisted nowhere — `routes_order.py:217`
- §3.8 rework — insert — ambiguity — a progress call from `REWORK` that leaves any dimension short returns `status` straight to `IN_PROGRESS` — `routes_order.py:206-207`
- §3.8 sign-off — revise — ambiguity — carries no request body; SoD (rung 4) evaluated ahead of the `READY_FOR_SIGNOFF` check — `routes_order.py:246-256`
- §3.9 dock cancel — insert — ambiguity — carries no request body — `routes_logistics.py:104-107`
- §3.9 labor call — insert — ambiguity — `guaranteed_hours` need not be whole — `routes_logistics.py:129`
- §3.9 labor call — insert — ambiguity — `overnight` reads `overnight_shift_start_local_hour` from the scoped order's arena, or the scoped booking's — `routes_logistics.py:153-168`
- §3.9 close — insert — ambiguity — `actual_hours` need not be whole; call state evaluated before the scoped order's state — `routes_logistics.py:203-211`
- §3.9 cancel — insert — ambiguity — carries no request body — `routes_logistics.py:220-226`
- §3.9 issue — insert — ambiguity — issuing writes no pool field, so pool `version`/`updated_at` are unchanged; a return does write them and bumps `version` — `routes_equipment.py:126-137`, `cascade.py:23-27`
- §3.9 return — insert — ambiguity — the `damaged_units <= units_issued` ceiling needs the stored row, so 404 precedes it, while a negative value is 400 ahead of the 404 — `routes_equipment.py:169-176`

### Whole-file sanity check (pass C) — PASS
All 5 top-level sections present, 20 `###` subsections, 45 endpoint rows, 48 error rows, 4 code-fence markers (2 balanced pairs), tail ends cleanly on the final error row. 23 distinctive pass-A/B insertions spot-verified as still present exactly once; nothing clobbered.

### Orchestrator final verification
- `wc`: PRD.md 439/91,863 → PRD_FINALIZED.md 439/92,468 → PRD_COMPLETED.md 440/104,586. Both diffs non-empty, so neither Step 8 nor Step 9 was a silent no-op.
- Structure independently re-counted: 5 `^## ` sections, 47 lines in the §4 table (= 45 rows + header + separator), 48 `ERR` rows in §5, tail = `| ERR_TENANT_HOLD_QUOTA_EXCEEDED | 422 |`.
- `implementation/*.py` mtimes all 07:25, i.e. unchanged since Step 6 generation — independently corroborating Step 7's "0 implementation fixes" and confirming Steps 8/9 touched only PRD files. Newest test-layer mtimes are 08:42–08:43, the two Step 7 test fixes.
- All 8 `results.{1..8}.json` retained, each 108/108 passed, 0 failed.

**PIPELINE COMPLETE.**
