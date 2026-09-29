# Worklog — task_2639_repertory_cinema_programming_rights_clearance

## Step 1: Create task directory — 2026-09-03T23:32:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2639_repertory_cinema_programming_rights_clearance` and its `workspace/` subdirectory. Index 2639 was pre-assigned by the caller; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T00:52:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Files**
- `SCAFFOLD.yaml` — 3147 lines (150,310 bytes)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2169 lines (157,951 bytes)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3515 lines (245,416 bytes)

**SCAFFOLD.yaml counts (§1.0–§1.7)** — `scenario` verbatim; `domain_name: repertory-cinema-programming-rights`; `api_prefix: "/"`; primary archetype `temporal_windowing`, secondary `multi_party_negotiation`; layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`; topology `flat`; shape `cyclic`; role model `segregation_of_duties`; consistency `immediate`.
- 13 entities, 10 state machines, 4 concurrency rules (OCC-only, 412), 11 calculations, 31 ordered validations, **61 endpoints**, 52 errors, 7 roles.
- Neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears as a key.

**§1.8 — 9 rules / 24 instances** (each rule >= 2, differentiated): dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 3, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 3.

**§1.9 — 9 sections / 64 instances** (54 with `test_recipe`, 10 `excluded_because` stubs, all citing an existing §1.8 instance by name): entities 11, state_machines 11, calculations 9, validations 13, endpoints 6, errors 3, rbac 3, cross_cutting_complexity_layers 7, consistency_model 1.

**Lint verdict (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    61
  §1.1 entities declared:     13
  §1.8 instances scanned:     24
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  863

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Audit-pass amendments made to SCAFFOLD.yaml while generating §1.9** (all §1.5/§1.3 corrections the design work exposed):
1. Added `"limit?", "offset?"` to the `input:` of the 9 list endpoints and `GET /bookings/{id}/offers` (needed for the pagination claim; previously would have failed lint check (c)).
2. Marked the six defaulted Venue fields optional in `POST /venues` `input:` (`house_hold_seats?`, `min_useful_gap_minutes?`, `utc_offset_minutes?`, `max_first_run_share?`, `weekly_repertory_target?`, `base_house_nut_weekly_cents?`) — §1.1 declares defaults for them, so the defaults claim requires them to be omittable.
3. Fixed an internal contradiction in `calculations.member_standing.variants[fiscal_ytd_standing].difference`: a 2026-03-01 gift yields `fiscal_tier PROSPECT`, not BASIC, since `FISCAL_YEAR_START` is 2026-07-01.

No sibling task directory was read, listed, globbed, or grepped at any point; every file was written by chunked `cat >>`/append, never a single giant Write.

## Step 3: Copy shared files — 2026-09-04T00:52:30.000Z

Copied `./INSTRUCTION.md` -> `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T01:08:00.000Z

`workspace/PRD.md` — **434 lines / 98,524 characters**. Built with 14 chunked heredoc appends plus 2 programmatic table appends — never a single large Write, so the 64k output cap was never in play.

**Orchestrator anti-truncation check (independent):** `grep '^## '` shows all five sections present (§1 line 3, §2 line 11, §3 line 179, §4 line 309, §5 line 377); `tail -12` ends on a complete, well-formed §5 error-table row (`| ERR_GUARANTEE_REQUIRED | 422 |`). Ends at a real section boundary — NOT truncated. No regeneration needed.

Verbatim last 3 lines:
```
| `ERR_CREDIT_BALANCE_INSUFFICIENT` | 422 |
| `ERR_HOUSE_NUT_ABOVE_CAP` | 422 |
| `ERR_GUARANTEE_REQUIRED` | 422 |
```

**Section list**
- §1. Introduction — pain points, system scope, two global design constraints (logical clock, integer cents)
- §2. Global Specifications & System-Wide Principles — 11 subsections: 2.1 RBAC · 2.2 API Response Structure · 2.3 Pagination · 2.4 Resource Identity, Auditing and the Logical Clock · 2.5 Money, Minutes and Rounding Discipline · 2.6 Stale-Version Guards on Negotiation, Licences and Settlement · 2.7 The Validation Ladder · 2.8 Venue-Local Time and the Programming Week · 2.9 Interval Geometry: Screen Blocks, Key Windows and Ingest Lanes · 2.10 Cascade Discipline, Recomputation and Conservation Invariants · 2.11 Path Resolution and Reference Agreement
- §3. Business Logic & Workflows — 9 subsections: 3.1 Establishing the House, Trading Partners and Catalogue · 3.2 Negotiating an Engagement Round by Round · 3.3 Clearing Repertory Rights · 3.4 Print Traffic, Ingest Lanes, Keys and the Booth · 3.5 Programming the Single Screen · 3.6 Special Event Production and Displacement · 3.7 Membership Standing and Donor Benefits · 3.8 The Box Office: Sales, Comps, Credit and Refunds · 3.9 Closing the Engagement and Settling with the Distributor
- §4. Endpoint Definitions — preamble + 61 rows (4 columns)
- §5. Error Code Catalogue — preamble + 52 rows (2 columns)

**Hard Contract reports (from generator)**
- Field-Name Coverage: `entities[].fields[].name` 136/136 present, 0 missing; `endpoints[].input` identifiers 101/101 present, 0 missing. PASS.
- Rule Coverage: 31/31 validations in explicit priority order with "first violated wins"; 4/4 concurrency rules with `expected_version` + 412; 10/10 state machines with every transition/guard/side effect; 11/11 calculations as step-ordered prose with constants in business context; every multi-hop cascade enumerated hop-by-hop (booking withdraw 4 hops, clearance revoke 3, KDM revoke 3, showtime cancel 2 + counters, special-event confirm 4). PASS.
- Path purity: 906 backtick tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos. PASS.

**Coverage vs SCAFFOLD.yaml:** 13/13 entities · 61/61 endpoints · 10/10 state machines · 11/11 calculations · 31/31 validations · 52/52 error ids · 7/7 roles.

**Judgement calls the doc generator resolved (PRD is now authoritative per PRD-First):**
- `OFFER_VALIDITY_HOURS` has no numeric value anywhere in SCAFFOLD.yaml -> PRD states **72 hours**. `MAX_NEGOTIATION_ROUNDS` inferred as **4** from validation 21's text; `MAX_TICKETS_PER_ORDER` is 10.
- `ERR_CLEARANCE_EXPIRED` is referenced by the clearance state machine but absent from the §1.6 catalogue -> PRD's lazy-expiry rule flips `CLEARED -> EXPIRED` then refuses with catalogued `ERR_CLEARANCE_NOT_CLEARED` (validation priority 7); the state flip persists even though the request failed.
- Scaffold uses `X-Role` in validations 1–2 while the skill mandates `X-User-Role` -> PRD uses `X-User-Role` exclusively.
- Booking-close actor contradiction (state machine `BoxOfficeManager` vs §1.5/§1.7 `ExecutiveDirector`) -> resolved to `ExecutiveDirector`.
- Settlement uniqueness contradiction (state machine vs validation 26's VOID reference, which Settlement lacks) -> PRD follows the state-machine reading only; a fresh DRAFT may supersede an earlier DRAFT.
- Validation 7 mentions a `DENIED` clearance state absent from the enum -> deliberately not invented.
- Eight unpaired preconditions were given coherent catalogue errors in prose (clear-after-window-end -> `ERR_CLEARANCE_INVALID_STATE`; key for unencrypted package -> `ERR_INVALID_REQUEST`; package/venue mismatch on key issue -> `ERR_REFERENCE_MISMATCH`; open-sales with no seats -> `ERR_INSUFFICIENT_SEATS`).

Withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped or referenced; no sibling task directory was read.

## Step 6: Generate implementation — 2026-09-04T01:52:00.000Z

Implementation complete and verified.

**Files (`workspace/implementation/`, 3174 lines of Python)**

| File | Lines | Role |
|---|---|---|
| `app.py` | 68 | Blueprint wiring, global store lock per request, ApiError/HTTPException/Exception handlers, `app.run(host=0.0.0.0, port=$PORT or 10000)` |
| `store.py` | 79 | In-memory dicts for all 13 collections, RLock, logical clock, id/record factories |
| `timeutil.py` | 101 | Instant/day parsing and formatting, venue-local conversion, ISO-week keys |
| `errors.py` | 78 | All 52 PRD error ids with HTTP statuses |
| `response.py` | 80 | Envelope, meta, pagination (limit 1..100 default 10, offset >=0) |
| `auth.py` | 70 | 7 roles, `X-User-Role`/`X-Role` fallback, per-endpoint authorization |
| `validate.py` | 246 | Field-level schema checks and reference lookups |
| `calc.py` | 454 | All 11 calculations: pricing, proration, film rent, weekly balance, slot scoring, member tiers, `round_half_up` on exact `Fraction`s |
| `serialize.py` | 158 | Wire serializers for all 13 entities |
| `cascade.py` | 102 | Multi-hop cascades with a version `Ledger` (one bump per row per operation) |
| `routes/catalog.py` | 127 | Venues, distributors, titles, clock |
| `routes/bookings.py` | 272 | Engagements + negotiation rounds/offers |
| `routes/clearances.py` | 173 | Rights clearance lifecycle incl. separation-of-duties |
| `routes/tech.py` | 212 | DCP assets, print traffic, KDM keys |
| `routes/showtimes.py` | 402 | Manual + auto-scheduler, 3 status dimensions, playback verification |
| `routes/events.py` | 156 | Special events, displacement, cancel compensation |
| `routes/orders.py` | 173 | Ticket orders, pay, refund |
| `routes/members.py` | 93 | Membership, donations, lapse sweeps |
| `routes/settlements.py` | 130 | Settlement drafting/submit/finalize/resolve |
| `start.sh` (9), `requirements.txt` (1) | | `exec python3 app.py` after a guarded flask install |

**Results**
- Endpoint coverage: 61/61 (`@bp.<verb>` decorator count matches the PRD endpoint table exactly).
- `python3 -m py_compile` on all 19 `.py` files: clean (`PY_COMPILE_OK`). `__pycache__` removed afterwards.
- Smoke boot: passed. Booted on high ports 18639 and 18641, killed by pid only each time (`kill <pid>`, never `pkill`); ports confirmed free after. ~140 end-to-end assertions passed across four scripted passes: envelope/meta shape, pagination guards, auth (incl. `ERR_UNAUTHENTICATED` for undeclared roles, anonymous public reads, Member own-record scoping), PRD-pinned arithmetic (unit 1233 / subtotal 3699 / fee 450 / total 4149; member discount 750 + 300 fee = 1050; credit application; min-run penalty 11250), the three interval geometries (half-open screen occupancy admits back-to-back, closed KDM validity rejects a touching interval, key expiring exactly at `end_at` still covers), the 31-step ladder ordering (OCC before window checks, format before collision, weekly first-run ceiling), auto-schedule winner + `slot_score` 94 + `ERR_NO_ELIGIBLE_SLOT`, special-event confirm/displace/cancel-compensation, KDM revoke fallback with sales pulled, booking-withdraw 4-hop cascade, and the full settlement cycle including `ERR_STALE_BOOKING_VERSION` (412) and PAID terminality.
- Fresh-process cleanliness confirmed on a final boot: every list endpoint returns `total_count: 0`, clock at the `2026-08-01T00:00:00Z` epoch, no seeded rows. Source scan found zero persistence primitives (no sqlite, no `open(`, no `json.dump`, no pickle, no `/tmp`), so per-test-server isolation gets a truly empty store every launch.

Three apparent failures during smoke testing were the generator's own script expectations, not implementation bugs — verified against the PRD: `box_office_cents` is the sum of `total_cents` (fee inclusive) with `cinema_retained_cents = adjusted_gross + facility_fees - film_rent`, FLAT_FEE raw rent is `guarantee_cents`, `ERR_FORMAT_UNSUPPORTED` is not a PRD error id (correct: `ERR_FORMAT_INCOMPATIBLE`), `resolve` takes `outcome` not `resolution`, and `POST /settlements` is BoxOfficeManager-only.

## Step 5: Generate unit tests — 2026-09-04T02:07:00.000Z

Both queues are translated and audited. Stage 1 + Stage 2 are complete.

**Output tree (task root, nothing under `workspace/` — orchestrator independently confirmed `workspace/` contains only INSTRUCTION.md, PRD.md, implementation/)**

**test_helpers/ — 2,241 lines**: `__init__.py` 41 · `types.py` 431 · `api_client.py` 258 · `api_errors.py` 117 · `constants.py` 125 · `test_users.py` 77 · `factories.py` 258 · `assertions.py` 288 · `fixtures.py` 746

**test_suite/ — 6,181 lines, 126 tests**
| file | lines | tests |
|---|---|---|
| `conftest.py` | 70 | — |
| `test_01_screen_geometry_and_slot_scoring.py` | 192 | 7 |
| `test_02_rights_clearance_and_weekly_balance.py` | 280 | 7 |
| `test_03_print_traffic_ingest_lanes.py` | 248 | 6 |
| `test_04_key_windows_and_booth_verification.py` | 322 | 8 |
| `test_05_box_office_pricing_and_seat_conservation.py` | 271 | 9 |
| `test_06_membership_standing_and_member_credit.py` | 155 | 6 |
| `test_07_showtime_dimensions_and_cascades.py` | 395 | 13 |
| `test_08_negotiation_closure_and_settlement.py` | 459 | 14 |
| `test_10_entity_contract_and_field_derivation.py` | 304 | 6 |
| `test_11_referential_integrity_and_enum_validation.py` | 257 | 5 |
| `test_12_lifecycle_transitions_and_side_effects.py` | 263 | 5 |
| `test_13_terminal_state_refusals_and_compensation.py` | 255 | 5 |
| `test_14_pricing_rollup_and_settlement_figures.py` | 391 | 6 |
| `test_15_licence_window_and_format_validations.py` | 287 | 5 |
| `test_16_box_office_and_membership_entitlement_validations.py` | 391 | 6 |
| `test_17_endpoint_round_trips_and_rollups.py` | 477 | 6 |
| `test_18_role_authority_and_error_reachability.py` | 470 | 6 |
| `test_19_optimistic_concurrency_and_read_your_writes.py` | 694 | 6 |

**Design-index coverage — no gaps, no skips**
- Queue A (difficulty): 24/24 instances translated, 0 skipped, **70 tests**. Every instance has >=2 tests (min 2, max 4).
- Queue B (corner): 54/54 non-stub instances translated, 0 skipped, **56 tests** (>=1 each). Section split: entities 11, state_machines 8, calculations 6, validations 11, endpoints 6, errors 3, rbac 3, cross_cutting 5, consistency_model 1.
- 10 `excluded_because:` stubs correctly emitted no tests; all 10 `difficulty_instance:` cross-references verified to resolve to real `rule_id / name` pairs.
- Every instance passed the PRD-first two-condition filter, so there are zero skip lines to report.

**Audits the generator ran itself**
- AST sweep of all 126 test functions: every one has a docstring, exactly one `Design:` line, last line. Zero untagged, zero dual-tagged, zero tags resolving outside the two indices, zero tags pointing at stubs.
- Citation pass: 176 quoted citations extracted from docstrings, all >=8 words, all 176 verbatim whitespace-normalized substrings of `workspace/PRD.md` (0 failures).
- `python3 -m py_compile` on all 28 generated `.py` files: all OK. `pyflakes` clean (only benign wildcard-import notices in `__init__.py`). Every test module imports successfully against the real `test_helpers`; all 43 distinct `ApiErrorId.*` members referenced exist.
- Zero occurrences of `scaffold`, `§1.x`, "Table N", `pytest.mark.skip`/`xfail`, `sys.path`, mocking, `X-Role`, or `ERR_CLEARANCE_EXPIRED`.

**Deliberate PRD-over-index deviations (hand-off to Step 7)**
1. KDM revoke cascade — index expects a PAID order refunded to member credit; PRD's hop three only voids `RESERVED` holds, so the test uses a RESERVED order -> `VOID`.
2. Booking withdraw — index says the clearance stays `CLEARED`; PRD says attached clearances become `REVOKED` with `revoked_reason` `BOOKING_WITHDRAWN`. PRD followed. The cascaded screening's `cancel_reason` is left unasserted (PRD self-contradicts).
3. Lapsed offer round — PRD moves the round's `outcome` to `EXPIRED`, not the index's `PENDING`; `expires_at` asserted as a 72h delta rather than an absolute literal.
4. Missing-role header — PRD does not uniquely derive 401 `ERR_UNAUTHENTICATED` vs 403 `ERR_FORBIDDEN_ROLE` for an anonymous caller on a privileged write, so that one test uses `validate_error_is_one_of([...])`.
5. Three non-derivable index assertions were dropped rather than weakened (a `cleared_at` field PRD never names; an explicit `*_INVALID_STATE` status where index says 422 and PRD §5 says 409 — the registered map governs; an absolute `clearance.version == 2` in auto-schedule, replaced by capture-and-compare). `ERR_KDM_NOT_FOUND` -> PRD's `ERR_KDM_KEY_NOT_FOUND`.

## Step 7: Run tests and iterate — 2026-09-04T02:20:00.000Z

Clean sweep achieved. All fixes were in the test artifact; the implementation needed no changes.

**Iterations run:** 2 (each a fully parallel 8-round `setsid` sweep, no early exit).

Iteration 1: 120/126 in every round — the same 6 failures in all 8 rounds, so zero flakiness; every failure was deterministic and load-independent.

**Tests deleted:** none. No failing test was PRD-silent or non-derivable at the whole-test level; all six were test-side defects fixable toward greater PRD fidelity.

**Fixes applied to `test_helpers/`**
- `test_helpers/fixtures.py`, `place_showtime()` — the five FK arguments were passed positionally to `showtime_payload()` from the `world` dict, so any test overriding one (`dcp_asset_id=...`) raised `TypeError: got multiple values for argument 'dcp_asset_id'` before a request was ever issued. Now each FK is `overrides.pop(<name>, world[...])`.
- `test_helpers/fixtures.py`, `auto_place_showtime()` — same latent defect in the optimiser fixture, fixed identically (pre-emptive; no test hit it yet).

**Fixes applied to `test_suite/`** (assertion-level, all made the test *more* faithful to PRD)
- `test_15_licence_window_and_format_validations.py`, `test_showtime_on_the_last_licensed_date_at_the_last_minute_is_accepted` — `assert_screen_block` expected `end_at` 20 minutes too late. PRD §3.5 gives `end_at = start_at + trailer_reel_minutes + runtime_minutes + extra_minutes`; the baseline house is 12 + 104 + 0 = 116 min, so from 22:00 the block is `23:56:00` / `00:21:00`, not `00:16:00` / `00:41:00`. Corrected the literals (the implementation was right).
- `test_16_box_office_and_membership_entitlement_validations.py`, `test_ticket_order_comp_seats_refused_for_a_basic_tier_member` — the order was posted with the shared `TEST_USERS["member_headers"]` (`X-User-ID: u-member-1`) while carrying `member_id` of the freshly enrolled member. PRD §2.1 requires a `Member`'s `X-User-ID` to equal the acting member's `id` and "any order they create must carry a `member_id` equal to their own `id`", so the PRD-faithful implementation correctly answered `ERR_FORBIDDEN_ROLE` at ladder rung 2 before reaching rung 20. Switched to `make_member_headers(member["id"])`; the comp-allowance assertion is unchanged and now reachable.
- `test_12_lifecycle_transitions_and_side_effects.py`, `test_licence_clearance_records_the_second_operator_and_bumps_the_version` — dropped only the trailing `assert data["updated_at"] > data["created_at"]` (STEP 1c partial-coverage split). PRD §2.4 says `updated_at` is "the instant of the most recent mutation" and that time is a server-held **logical** clock starting at `2026-08-01T00:00:00Z`; with the clock unmoved, a faithful implementation stamps both fields from that same logical instant, so strict inequality is not uniquely derivable (two PRD-consistent readings: logical-clock stamps vs host-wall-clock stamps). All substantive assertions in that test — `CLEARED`, `submitted_by_user_id` unrewritten, `cleared_by_user_id`, allowance untouched, `version == 2` — were kept.

**Fixes applied to `implementation/`:** none. No PRD-required check was removed or weakened, no endpoint/field/side-effect was added, and storage remains in-memory only.

**Final sweep evidence** (all in `workspace/implementation/`, timestamped 02:18): results.1..8.json each 126/126.

**Orchestrator independent verification:** `ls -la` confirms all 8 files present (43,994–44,004 bytes each, 02:18); parsing each JSON gives `passed=126 total=126 failed=0` for every round. Union of failures across all 8 rounds is empty.

## Step 8: Finalize PRD — 2026-09-04T02:31:00.000Z

`PRD_FINALIZED.md` written: 434 lines (identical to PRD.md's 434; +1,223 chars, +1.24% by size, 0.00% by line count), ending on the complete §5 error table (`ERR_GUARANTEE_REQUIRED | 422`).

**Changes (3 edits, from 4 step_7_diff items)**
- §2.1 (identity semantics) — *insert* — pinned that a `Member` ownership-comparison failure is `ERR_FORBIDDEN_ROLE` (403), and pinned *where* it sits relative to other checks: body-named `member_id` is compared as soon as it is read (before remaining body fields, before FK resolution, before the state/seat/comp/credit rungs), path-named records are compared after the path id resolves, list filters are compared against the supplied value — `auth.py:67-70`, `routes/orders.py:31-38,110-111,122-126,135-136`, `routes/members.py:52-54`.
- §2.4 (resource identity/audit) — *insert* — `created_at`/`updated_at` are stamped from the logical clock, not host wall clock, so a mutation with the clock unmoved leaves `updated_at == created_at` while `version` advances — `store.py:52-69` (`new_record`, `touch`).
- §2.3 (pagination/ordering) — *revise* — added the `created_at` tie-break (creation sequence, oldest first), a direct consequence of making logical-clock stamping explicit — `store.py:72-74` (`ordered()`).

**No edit** for two step_7_diff items: the `test_helpers/fixtures.py` `place_showtime()`/`auto_place_showtime()` positional-FK `TypeError` was a pure fixture defect (no request ever issued, no impl behaviour involved); and the test_15 `end_at`/`blocked_until` literals were a test arithmetic error against a rule §3.5 already determines verbatim (`compute_block` in `calc.py:90-97` matches the PRD formula exactly), so the prose was left untouched.

**Per-edit pre-edit search log**

Edit 1 — Member ownership refusal
- (a) Subject: the `Member` role's ownership comparison — which error it yields and at which ladder position, on every endpoint a `Member` may call.
- (b) Enumerated: grepped `require_own_member|ROLE_MEMBER|member_id` across all of `implementation/`. Read `auth.py:49-70` (`authorize`, `require_own_member`), `routes/orders.py` in full (create/read/list/pay/refund), `routes/members.py:50-64`, `validate.py` (`body`, `opt_id`, `req_int`, `must_find`), `calc.py:200-202`. Confirmed the five live callsites: `create_order` (body, before `req_int quantity`/`must_find`), `read_order` (after `must_find`), `list_orders` (query filter + unconditional own-rows filter), `pay_order` (after `must_find`, before state), `read_member` (after `must_find`). Confirmed no `Member` role on `/members/{id}/donations`, `/ticket-orders/{id}/refund`, or any other endpoint.
- (c) Adjustment: first draft said the check runs "at rung 2, before any schema, existence or state check." The enumeration showed that is false for the four path/filter callsites, where `must_find` (404) precedes it, and false in `create_order` for JSON-parse/`member_id`-type errors. Re-scoped into three explicit cases (body / path / filter) and anchored the body case to "as soon as that `member_id` field has been read" rather than "before schema." Deliberately left the parallel `Anonymous`-carrying-`member_id` -> `ERR_FORBIDDEN_ROLE` branch (`routes/orders.py:36-38`) unpinned, since the sentence is scoped to `Member` and makes no exclusive claim about other roles.

Edit 2 — logical-clock audit stamps
- (a) Subject: every writer and reader of `created_at`/`updated_at`.
- (b) Enumerated: grepped `created_at|updated_at|touch\(|now\(\)` across all of `implementation/`. Writers are exactly `store.py:56-57` (`new_record`) and `store.py:67` (`touch`), both `db.clock`; no route or helper assigns either field. Readers: `store.py:74` (`ordered`), `routes/bookings.py:75` (`expires_at = created_at + 72h`), `serialize.py:9-10`. Cross-checked `response.py:24-28` — `api_request_timestamp` uses real wall clock, so the sentence was scoped to "both of those instants" only. Cross-checked `cascade.py:15-28` (`Ledger.flush` -> `touch`) so the cascade case is covered.
- (c) Adjustment: none needed; wording already scoped to the two audit fields and makes no claim about `api_request_timestamp`, `received_at`/`ingested_at` or `expires_at`.

Edit 3 — list tie-break
- (a) Subject: the ordering of every list endpoint's result set.
- (b) Enumerated: grepped `paged\(|ordered\(`. Every paged endpoint (`titles`, `bookings`, `clearances`, `dcp-assets`, `kdm-keys`, `showtimes`, `special-events`, `ticket-orders`, `settlements`) passes through `store.ordered()` = sort by `(created_at, _seq)` with `_seq` a monotonic creation counter. The one exception, `GET /bookings/{id}/offers`, uses `booking_rounds()` sorted by `round_index` (`routes/bookings.py:23-25`), itself creation order — consistent with the new clause; the existing "likewise oldest-first" sentence was preserved verbatim.
- (c) Adjustment: phrased the tie-break as "the sequence in which they were created" rather than naming an internal counter or claiming a total order over `id`, keeping the primary key `created_at` ascending so a backward clock move still sorts by stamp first, exactly as `ordered()` does.

**Orchestrator verification:** PRD_FINALIZED.md is 434 lines (>= source's 434) and still ends on the complete §5 error table.

## Step 9: Complete PRD — 2026-09-04T02:56:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/` rather than one monolithic subagent: on an implementation this size a single pass reliably degenerates into a shallow scan (or a byte-identical no-op copy of the source PRD). Partition: pass 1 = infrastructure/global semantics (`app.py`, `store.py`, `timeutil.py`, `errors.py`, `response.py`, `auth.py`, `validate.py`, `serialize.py`, `cascade.py`); pass 2 = `calc.py` + `routes/{catalog,bookings,clearances}.py`; pass 3 = `routes/{tech,showtimes,events,orders,members,settlements}.py`. Each pass edited `PRD_COMPLETED.md` in place with targeted Edits and was told which items earlier passes had already adjudicated, so no work was redone and no pass rewrote the file wholesale.

**Totals: 40 edits — 31 ambiguity-pins, 9 mismatch-revisions.** `PRD_FINALIZED.md` 434 lines / 99,747 chars -> `PRD_COMPLETED.md` 434 lines / 110,956 chars (+11,209 chars, +11.2%; 78 diff lines = 39 paragraphs revised in place, zero new lines or sections).

### Pass 1 — infrastructure / §2 (10 ambiguity-pins, 1 mismatch)
- §2 intro — insert — ambiguity — inbound instant-parsing contract (any parseable ISO 8601 normalised to UTC, incl. explicit offsets and zone-less read as UTC, any fractional-digit count; sub-ms truncated not rounded on echo) plus `YYYY-MM-DD` / `HH:MM` wire widths — `timeutil.py:12-68`
- §2.1 — insert — ambiguity — empty/whitespace `X-User-Role` = anonymous; undeclared role is 401 even where `Anonymous` is admitted; empty `X-User-ID` counts as missing on the SoD endpoint — `auth.py:29-63`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase alphanumerics, minted per response incl. errors — `response.py:17-28`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the **host wall clock**, not the logical clock — `response.py:24-28`
- §2.3 — insert — ambiguity — negative/mistyped `offset` is `ERR_INVALID_REQUEST` with no upper bound; omitted/empty params take defaults; boolean filters accept `true/false/1/0` case-insensitively, instant filters must parse, unmatched-but-valid values give an empty page; paging validated **after** path resolution — `response.py:55-73`, `validate.py:205-224`
- §2.3 — insert — ambiguity — oldest-first ordering also governs id lists returned by batch capabilities (swept membership ids) — `store.py:72-74`
- §2.4 — insert — ambiguity — a read is never a mutation: advances neither `updated_at` nor `version`, incl. reads that re-derive stored fields from the clock — `serialize.py:145-147`, `calc.py:216-243`
- §2.4 — insert — ambiguity — clock-setting response is a non-resource object with the single field `current_utc`; any parseable instant accepted forward or backward — `routes/catalog.py:121-127`
- §2.5 — **revise — mismatch** — PRD claimed comparisons "at millisecond resolution"; impl compares at whatever precision the client supplied — `timeutil.py:12-27`
- §2.7 step 3 — insert — ambiguity — absent/empty write body read as `{}`; non-JSON/non-object body is `ERR_INVALID_REQUEST`; required strings must be non-empty after trimming; bool<->int checking strict both ways, integer accepted for a share fraction — `validate.py:21-99`
- §2.10 — insert — ambiguity — version accounting unit is the **operation** not the hop; a cascade-recomputed row is touched only when a stored field actually moves; a released hold with nothing to return does not touch its member, but a cascade reversing a *paid* order always does — `cascade.py:15-90`, `calc.py:310-329`

### Pass 2 — calc.py + catalog/bookings/clearances (10 ambiguity-pins, 3 mismatches)
- §3.9 — **revise — mismatch** — the step-six worked example was arithmetically impossible (nut 12500 with min_run 4 / 1 day played gives 7500, not the quoted "11250, not 4688"); both quoted figures come from a nut of **18750**, so the example's nut was corrected — `calc.py:354-358`
- §3.2 — **revise — mismatch** — withdrawal's `cancel_reason` was said to propagate onto cascade-cancelled screenings; impl stores it on the engagement and passes the literal `CLEARANCE_REVOKED` to screenings — `routes/bookings.py:253-270`
- §3.7 — **revise — mismatch** — `expires_at` was pinned to "that donation's `received_at`"; impl always re-derives from the **latest** donation instant, so a backdated gift behind a later one does not move it — `calc.py:238-242`
- §3.1 — insert — ambiguity — `utc_offset_minutes` may be negative and is unbounded (the §2.7 blanket non-negative-minutes rule would otherwise forbid it); it is the only signed-int field in the service — `routes/catalog.py:40`
- §3.1 — insert — ambiguity — `open_local_time`/`last_start_local_time` get no ordering check, stored as posted — `routes/catalog.py:38-39`
- §3.1 — insert — ambiguity — `contact_email` validated only as a non-empty string — `routes/catalog.py:63`
- §3.2 — insert — ambiguity — the pending-round requirement is evaluated **after** the OCC guard and the from-state, so a state admitting neither counter nor offer reports `ERR_BOOKING_INVALID_STATE` — `routes/bookings.py:167-170`
- §3.2 — insert — ambiguity — sign-off's from-state is tested ahead of the three round conditions — `routes/bookings.py:202-203`
- §3.3 — insert — ambiguity — `license_fee_cents` is a recorded obligation only, entering no settlement figure — `routes/clearances.py:52`
- §3.3 — insert — ambiguity — re-lodging does not clear `change_request_note` — `routes/clearances.py:114-123`
- §3.3 — insert — ambiguity — for the same caller who lodged the licence, the window refusal wins over segregation of duties — `routes/clearances.py:146-151`
- §3.3 — insert — ambiguity — only the two schedulers discover the lazy lapse; reads and lists never flip `CLEARED -> EXPIRED` — `routes/clearances.py:33-44`
- §3.5 — insert — ambiguity — day/ISO-week membership in slot scoring is by the screening's own `start_at` (a block spilling past midnight belongs to its start day); cancelled screenings ignored in every component incl. the repertory strand bonus — `calc.py:116-142,428-431`
- §3.9 — insert — ambiguity — `proration_factor` is the one non-integer settlement figure, emitted as a JSON double, so a non-terminating ratio reaches the wire as `0.6666666666666666` — `calc.py:407`

Pass 2 also resolved pass 1's two deferred `calc.py` items: `recompute_showtime`'s `status == "SCHEDULED"` guard on the ON_SALE/SOLD_OUT oscillation is **unobservable** (every caller reaching it with a non-scheduled screening has already forced `sale_status` to `SALES_CLOSED`, and `open_sales` guarantees >=1 free seat), so no edit; `refresh_member`'s latest-donation derivation became the §3.7 mismatch revision above.

### Pass 3 — tech/showtimes/events/orders/members/settlements (12 ambiguity-pins, 5 mismatches)
- §2.7 step 6 — **revise — mismatch** — the sale-dimension check was listed under step 6; step 6 only guards "screening is not `SCHEDULED`", the sale-status refusal is step 25 — `routes/orders.py:46-48` vs `:71-73`
- §2.7 step 24 — **revise — mismatch** — `ERR_REFERENCE_MISMATCH` was claimed for settlement and ticket-order creation, which never raise it; list now covers both schedulers, key issue, clearance creation and the `supersedes` reference — `routes/settlements.py:32-64`, `routes/tech.py:144`
- §3.5 — **revise — mismatch** — PRD framed licence state / allowance / format / window as per-slot optimiser filters (implying `ERR_NO_ELIGIBLE_SLOT`); impl refuses them once up front with their own ladder errors, and only operating window / past clock / collision / weekly ceiling silently drop slots; added the pre-grid `ERR_SHOWTIME_WINDOW_INVALID` when the target date's `latest_local_time` is already past — `routes/showtimes.py:196-262`
- §3.6 — **revise — mismatch** — "operating day" pinned to the midnight ending the screening's venue-local start date, inclusive, with no comparison against `last_start_local_time` — `routes/events.py:109-113`
- §3.7 — **revise — mismatch** — `ERR_MEMBER_INVALID_STATE` is declared but unreachable: donations are accepted at any status and the sweep skips non-`ACTIVE` members — `routes/members.py:58-88`
- §3.4 — insert — ambiguity — all six chain statuses are valid `new_status` values, so same/behind/skip-ahead is `ERR_DCP_ASSET_INVALID_STATE` while only an off-chain string is `ERR_INVALID_REQUEST`; `RETURNED` admits no update — `routes/tech.py:96-124`
- §3.4 — insert — ambiguity — lazy expiry of candidate keys happens after the two state checks and persists (own `version` bumped) even when verification then fails — `routes/showtimes.py:300-330`
- §3.5 — insert — ambiguity — `earliest_local_time == latest_local_time` searches a single slot; only strictly-earlier `latest` is `ERR_INVALID_REQUEST` — `routes/showtimes.py:205-210`
- §3.5 — insert — ambiguity — a collapsed event copies the screening's supplied `cancel_reason`; a `CONFIRMED` event killed this way is not compensated — `routes/showtimes.py:352-372`
- §3.5 — insert — ambiguity — `start_from`/`start_to` compare inclusively against `start_at` — `routes/showtimes.py:170-180`
- §3.6 — insert — ambiguity — `displaced_showtime_ids` appended in canonical (oldest-first) order — `routes/events.py:100-127`
- §3.6 — insert — ambiguity — compensation applies whatever state the wrapped screening now holds, incl. an already-cancelled one — `routes/events.py:145-154`
- §3.8 — insert — ambiguity — per-role `member_id` rules, with an `Anonymous` caller supplying it refused `ERR_FORBIDDEN_ROLE` before the rest of the body is read — `routes/orders.py:33-38`
- §3.8 — insert — ambiguity — the member row's `updated_at`/`version` move only when credit or comps were actually consumed — `routes/orders.py:96-100`
- §3.8 — insert — ambiguity — a refund always touches the named member, even a `CASH` one with no credit and no comps — `routes/orders.py:165-170`
- §3.7 — insert — ambiguity — duplicate-email test is exact string comparison (no case folding, no trimming); `LAPSED` addresses are reusable — `routes/members.py:24-27`
- §3.9 — revise — ambiguity — `dispute_note` is required only with a `DISPUTED` outcome; sent with `PAID` it is ignored and any earlier note stays — `routes/settlements.py:119-129`

**Final structural verification (pass 3 + orchestrator, independently):** `PRD_COMPLETED.md` 434 lines / 110,956 chars; ends on the complete row `| ERR_GUARANTEE_REQUIRED | 422 |`; §5 has all 52 error rows, §4 all 61 endpoint rows, all five top-level sections present (§1 L3, §2 L11, §3 L179, §4 L309, §5 L377); `cmp` confirms it is NOT byte-identical to `PRD_FINALIZED.md` (78 diff lines), so the scan genuinely ran.

**Green-sweep integrity:** `find` over `test_suite/`, `test_helpers/` and `workspace/implementation/` (excluding `results.*.json`) shows zero files modified after 02:19 — Steps 8 and 9 touched documentation only, so the 8/8 x 126/126 sweep from 02:18 still describes the shipped artifacts.

Two findings flagged for upstream generator feedback: (1) the doc generator emitted an arithmetically impossible worked example in §3.9's min-run penalty (a Zero-Silence-Rule example that does not evaluate); (2) `ERR_MEMBER_INVALID_STATE` is declared in the scaffold's error catalogue but is unreachable in any PRD-faithful implementation, and `ERR_REFERENCE_MISMATCH`'s declared `applies_to` scope was wider than any reachable code path.

## Pipeline complete — 2026-09-04T02:56:00.000Z

All nine steps finished. Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 files, 2,241 lines), `test_suite/` (18 test files + conftest, 6,181 lines, 126 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`, `workspace/implementation/` (19 .py files + start.sh, 3,174 lines), and `workspace/implementation/results.{1..8}.json` all at 126/126.
