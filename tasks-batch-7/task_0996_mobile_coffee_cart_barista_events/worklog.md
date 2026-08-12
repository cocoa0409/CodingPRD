# Worklog — task_0996_mobile_coffee_cart_barista_events

## Step 1: Create Task Directory — 2026-08-10T12:23:06.134Z

Pre-assigned output folder `tasks/task_0996_mobile_coffee_cart_barista_events` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per headless-run instructions. Nothing created.

## Step 2: Generate Scaffold — 2026-08-10T12:53:40.225Z

Scaffold generation complete. Lint verdict: `clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5`.

## Summary

**Output files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_0996_mobile_coffee_cart_barista_events/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design` key

**Counts**

| Section | Count |
|---|---|
| Entities | 13 (Client, CoffeeCart, Barista, Package, AddOn, TravelZone, EventBooking, BookingAddOn, BaristaAssignment, InventoryItem, InventoryReservation, Payment, CancellationPolicyTier) |
| State machines | 4 (EventBooking with 7-state cycle/branching, BaristaAssignment with re-offer cycle, InventoryReservation fork-join, Payment linear) |
| State transitions | 30 total |
| Calculations | 12 (dual-variant pricing, dual-variant travel fee, dual-variant refund, deposit clamp, weekly hours threshold, cart/barista overlap, inventory availability, add-on skill gate, payment/inventory invariants) |
| Validations | 24 (priority-ordered across auth/existence/state/business_temporal/constraint/referential/fiscal) |
| Endpoints | 54 (full CRUD + lifecycle actions + logical clock test-driver) |
| Errors | 29 (domain-specific codes) |
| Roles | 3 (OperationsManager opaque, Client entity-backed, Barista entity-backed) |
| Concurrency rules | 2 OCC rules (cart version + primary barista version on booking submit) |
| Difficulty instances | 19 across all 9 rules (Rule 2 has 3 instances — one per mode a/b/c) |
| Corner instances | 23 across 8 taxonomy sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers) |

**Harder-than-expert difficulty levers exercised:**
- Three combinatorial-formula modes (threshold-clamp with 3 interacting inputs, nested rounding with order-dependence, circular-dependency evaluation order)
- Two cyclic state machines on different entities (booking amend loop, assignment re-offer loop)
- Two transitive cascades from distinct triggers (cancel → assignment → barista hours; payment success → booking → assignment + reservation)
- Two distinct interval-overlap semantics (buffered cart vs unbuffered barista, both half-open)
- Two compensating invariants on distinct conserved quantities (inventory units, barista weekly hours)
- Two priority-pair conflicts across different error-category pairs
- Two boundary checks on distinct metrics (cart buffer minutes, inventory units)

## Step 3: Copy Shared Files — 2026-08-10T12:54:00.610Z

Copied `./INSTRUCTION.md` → `tasks/task_0996_mobile_coffee_cart_barista_events/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T13:05:08.258Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_0996_mobile_coffee_cart_barista_events/workspace/PRD.md`. The withheld difficulty/corner design files were not opened or referenced at any point.

## Summary

**Structure**: 5 top-level sections; §2 has 10 subsections (2.1 Roles/Auth, 2.2 Response Structure [verbatim], 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock, 2.6 Money & Rounding, 2.7 OCC on Submission, 2.8 Nested Retrieval, 2.9 Catalog Status Gating, 2.10 Validation Order); §3 has 8 subsections organized by booking lifecycle (catalog → quoting/outfitting → pricing → staffing → submit/reopen → deposit-to-event-day → wrap-up/reconciliation → amendment/cancellation/refunds). §4 endpoint table (4 columns, 54 rows = all 54 scaffold endpoints); §5 error catalogue (2 columns, 29 rows = all 29 scaffold errors).

**Size**: 284 lines (~46 KB).

**Coverage of scaffold elements**: all 13 entities with every field name (including computed fields like `committed_event_count`, `quoted_*`, `deposit_due_cents`, and the `common_fields: false` exception for BookingAddOn/Payment called out explicitly); all 4 state machines with every transition's preconditions and side effects; all 12 calculations translated to precise prose with constants embedded in context (1.5 cups/guest, 25 km metered threshold, 30% deposit clamped to 1,000–50,000 cents, 168-hour/7-day notice boundary with 0.5 short-notice haircut, 90-minute travel buffer, 24-hour lead time, 48-hour amend window); both OCC rules; all 24 prioritized validations with ordering stated where they share endpoints; both invariants (payment reconciliation, inventory conservation); all 3 roles with identity translations; clock default 2026-05-01T00:00:00Z with no wall-clock fallback.

**Hard Contract Reports**:

```
Field coverage check:
- entities[].fields: 83 required, 83 present, 0 missing
- endpoints[].request_body/input: 96 required total (incl. query/path params), 96 present, 0 missing
- endpoints[].query_params: all present (limit, offset, status, skill_level, pricing_model, client_id, cart_id, package_id, travel_zone_id, kind)
Status: PASS

Rule coverage check:
- validations[] with priority: 24 checked, 24 expressed in prose (global order in §2.10; per-endpoint orders in §3.2/3.4/3.5), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (submit + expected_cart_version/expected_primary_barista_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 31 checked (11 EventBooking, 11 BaristaAssignment, 6 InventoryReservation, 2 Payment + initial/terminal states), 31 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed in precise prose (reconstruction-tested), 0 missing
- validations[] conditions: 24 checked, 24 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 54 checked, 54 expressed, 0 missing
- entities[].fields[] structured content: 83 checked, 83 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (FLAT/PER_CUP, METERED/BANDED, forward-looking/chronological refund, 3 cancel sources, attended true/false, payment kind gates), 6 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 449
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot-checks passed: §2.2 matches the fixed block byte-for-byte (verified programmatically); all 47 enum/state/code values appear verbatim; all 29 error IDs appear in §2/§3 narrative; no fuzzy/approximating words; no pseudocode operators (`==`, `>=`, `+=`, `->`, etc.) in prose; PRD ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-10T13:33:32.801Z

Generation complete. Final summary:

## Deliverables

**`/home/ubuntu/github/CodingPRD/tasks/task_0996_mobile_coffee_cart_barista_events/test_helpers/`** (Stage 1):
- `types.py` — 13 entity TypedDicts + 12 status/variant enums; `BookingAddOn`/`Payment` correctly carry only `id`+`created_at` (no `updated_at`/`version` per PRD §2.4)
- `api_client.py` — 58 endpoint methods covering the full PRD §4 surface under `/coffee-cart`
- `api_errors.py` — all 29 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py` (CUPS_PER_GUEST=1.5, METERED_MAX_KM=25, deposit clamp 1000/50000, TRAVEL_BUFFER_MINUTES=90, etc.)
- `test_users.py` — opaque OperationsManager constant + `make_client_headers`/`make_barista_headers` entity-backed builders (identity threading enforced in fixtures)
- `fixtures.py` — composite chains: `setup_base_catalog` → `create_quote_booking`/`offer_primary_assignment` → `submit_quote` (fresh OCC version threading) → `pay_deposit` → `setup_confirmed_booking` → `setup_completed_booking`

**`test_suite/`** (Stage 2): `conftest.py` + 7 numbered files, **65 tests**, collected cleanly by pytest.

## Coverage
- **Queue A (Difficulty): 42 tests over 19/19 instances** (≥2 each; combinatorial_formula has 3 instances) — 0 skipped
- **Queue B (Corner): 23 tests over 23/23 non-stub instances** — 0 skipped (the corner index contains no `excluded_because:` stubs)

Audit script verified: every test has exactly one `Design:` tag (final docstring line) resolving to a real instance; every quoted PRD citation has a verbatim ≥8-word window in PRD.md; no skip/skipif/xfail markers; no scaffold references in generated code.

## PRD-first filter outcomes (judgment calls, no full skips)
1. **`client_creation_required_fields`** — dropped the `version == 1` assertion: this PRD's §2.4 never states the initial version value (unlike sibling-task PRDs). Remaining claims (201, UUID, status ACTIVE) are PRD-derivable.
2. **`reopen_after_deposit_paid_rejected`** — the scenario is a CONFIRMED booking; §2.10 validation order vs §3.5's `ERR_DEPOSIT_ALREADY_PAID` sentence leaves two faithful readings, so per the error-precedence silence pattern the test uses `validate_error_is_one_of([ERR_INVALID_STATE, ERR_DEPOSIT_ALREADY_PAID])`.
3. **`cart_buffer_adjacency_boundary_90min`** — the instance's own assert block is self-contradictory (claims +2h clears, then rechecks and finds collision). I translated the mathematically correct boundary from PRD §3.5's strict-before buffered rule: 13:29 rejected, 14:59 rejected, 15:00 exactly (event_end + 2×90min) allowed.
4. **`cross_entity_state_dependency` (both instances)** — the non-ACTIVE side (cart MAINTENANCE, barista ON_LEAVE) is unreachable via PRD endpoints, as the instances themselves note; I translated the reachable success-path assertions plus adjacent covered claims (`committed_event_count` derivation, unknown-`barista_id` → 404).
5. **ISO-week guard** — PRD §3.1 scopes `committed_hours_this_week` to the current ISO week while §3.4 states the accept effect unconditionally. Every committed-hours assertion books events inside the pinned clock's ISO week (2026-05-02/03 vs clock 2026-05-01), so both faithful implementations agree on the asserted values.

## Step 6: Generate Implementation — 2026-08-10T13:33:32.801Z

Everything verified. Fresh boots start with an empty store, and the full E2E suite (covering every tricky design-doc scenario) passes. The implementation directory contains only the three deliverables — no persistence artifacts.

## Summary

**Files generated** (all under `/home/ubuntu/github/CodingPRD/tasks/task_0996_mobile_coffee_cart_barista_events/workspace/implementation/`):

| File | Purpose |
|---|---|
| `app.py` (~1200 lines) | Complete Flask implementation: envelope helpers, auth middleware, pagination, derived-field serializers, pricing/refund engines, all state machines and cascades, 54 routes |
| `start.sh` | Executable launcher — guarded dependency install (`if ! python3 -c "import flask"`, with `--break-system-packages` fallback for PEP 668 environments), then `exec python3 app.py` |
| `requirements.txt` | `flask>=3.0` |

**Endpoint count: 54** (matches scaffold §1.5 exactly): 25 catalog (clients, carts, baristas, packages, addons + reverse booking-addons, travel-zones, inventory-items + reverse reservations, cancellation-tiers), 15 booking-lifecycle (CRUD, addons/assignments/reservations sub-resources, submit/reopen/amend/cancel/complete), 5 assignment actions, 3 reservation actions, 5 payment endpoints, 1 logical-clock endpoint.

**start.sh contract confirmed**: reads `$PORT` (default 10000), binds `0.0.0.0`, runs in foreground via `exec`. Boot-to-HTTP is ~2s; install is a no-op once Flask is importable, so per-test-server reboots are cheap. Storage is in-memory dicts only — verified that a kill/relaunch cycle yields an empty store (`total_count: 0`), with no SQLite/JSON/tmp persistence and zero startup seeding.

**Key fidelity decisions** (validated by an 80-assertion E2E run replaying the corner/difficulty design recipes):
- Exact envelope: `meta.api_request_id/api_request_timestamp`, `response_type`, `data`; error body `data.error_id/message`; list meta `limit/offset/total_count/has_more` (default 10/0, clamp 1–100); BookingAddOn and Payment carry only `id`+`created_at` (no `version`/`updated_at`).
- Logical clock pinned at `2026-05-01T00:00:00Z`; clock-set eagerly drives CONFIRMED→IN_PROGRESS.
- Submit guard order per PRD §3.5: state → catalog liveness → buffered cart overlap (±90 min, strict half-open) → add-on skill gate → staffing presence → zone subtotal gate (subtotal computed pre-fee) → dual OCC (`expected_cart_version`, `expected_primary_barista_version` → 412); successful submit reprices, pins `pricing_variant_used`/`travel_variant_used`, and bumps booking+cart+primary-barista versions.
- Exact math: `ceil(guests*3/2)` cups before multiply, deposit `round_half_up(30%)` clamped [1000, 50000], refunds `floor(deposit*pct)` with the 0.5 short-notice haircut under 168h, half-open barista overlap with adjacency allowed, inclusive inventory boundary.
- Verified live: deposit 18600/8700 figures, totals 62000/29000/27900, refund pair 18600 vs 4650, clamp branches 1000/18000/50000, idempotent replay returning the same Payment row, confirm/cancel/amend cascades with derived `committed_hours_this_week`/`reserved_units`/`committed_event_count`, and auto-created BALANCE/REFUND payments.

## Step 7: Run Tests and Iterate — 2026-08-10T13:41:32.934Z

All 8 parallel rounds pass 65/65 with zero failures and zero errors. Clean sweep confirmed by reading all 8 results files.

**Summary**

- **Iterations run:** 2 (sweep 1: 62–63/65 per round with 3 distinct failing tests; sweep 2 after fixes: 8/8 rounds at 65/65).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `fixtures.py` — `create_quote_booking`: extracted identity overrides (`client_id`, `package_id`, `cart_id`, `travel_zone_id`) from `**booking_overrides` via `pop` before the positional call into `create_booking_payload`. The old code passed `ctx["cart"]["id"]` positionally AND forwarded a caller-supplied `cart_id=` kwarg, raising `TypeError: got multiple values for argument 'cart_id'` in `test_back_to_back_assignments_for_same_barista_allowed` and `test_overlapping_assignment_for_same_barista_rejected` (failed deterministically in all 8 rounds). Both tests assert PRD §3.4's half-open barista-overlap rule (verbatim-quoted in their docstrings) and need to place booking two on a second cart — a PRD-legal construction — so this was a fixture bug, not an implementation bug.

- **Fixes applied to `test_suite/`:** none.

- **Fixes applied to `implementation/`:**
  - `start.sh` — replaced the flask presence guard `python3 -c "import flask"` (~600 ms, a full interpreter + flask import per reboot) with `importlib.util.find_spec("flask")` (~30 ms). With per-test-server isolation, start.sh runs before every one of 65 tests × 8 concurrent rounds (~520 boots/round); the old guard doubled per-boot import cost under 8× CPU contention and intermittently pushed a boot past the runner's 15 s readiness poll, surfacing as the flaky "API server could not be restarted" setup failure on `test_per_cup_total_equals_subtotal_when_distance_zero` (rounds 1, 2, 4, 5; the test itself passed whenever the server booted in time). No app logic changed; the start.sh contract (PORT / 0.0.0.0 / foreground / in-memory only) is intact.

## Step 8: Finalize PRD — 2026-08-10T13:43:40.658Z

Both Step-7 items are confirmed as non-PRD-silence items, and `PRD_FINALIZED.md` stands as a byte-identical copy of `PRD.md` with zero edits — the explicitly sanctioned outcome for this case.

## Analysis

**Item 1 — `test_helpers/fixtures.py` `create_quote_booking` (pure fixture bug):** The fix popped identity overrides (`client_id`, `package_id`, `cart_id`, `travel_zone_id`) before the positional call into `create_booking_payload`, resolving a `TypeError`. The two unblocked tests assert PRD §3.4's half-open barista-overlap rule verbatim, and the implementation (`barista_double_booked`, `workspace/implementation/app.py:458-469`) implements exactly that rule (`b["_es"] < ob["_ee"] and ob["_es"] < b["_ee"]`, adjacency allowed) — PRD §3.4 already uniquely pins this behavior ("the candidate's start falls before the other event's end and the other event's start falls before the candidate's end. Back-to-back events are explicitly allowed"). No PRD silence, no PRD/impl mismatch → no edit.

**Item 2 — `implementation/start.sh` (boot-speed optimization, no app-logic change):** Swapping `python3 -c "import flask"` for `importlib.util.find_spec("flask")` changed only how fast the dependency presence check runs. The start.sh contract (PORT / 0.0.0.0 / foreground / in-memory) is governed by `INSTRUCTION.md`, not the PRD. The PRD's only startup-adjacent claim is §2.5's logical clock initializing to `2026-05-01T00:00:00Z` — that logic lives in `app.py`, which was not touched. The flaky failure it fixed (`test_per_cup_total_equals_subtotal_when_distance_zero`) was a boot-timeout setup failure; the underlying pricing rule (distance 0 ≤ 25 km → `METERED`, fee = `distance_km * per_km_rate_cents` = 0; `app.py:427-429`) is already pinned verbatim by PRD §3.3. No PRD silence, no mismatch → no edit.

## Exit summary

- **Line counts:** `PRD.md` = 284 lines; `PRD_FINALIZED.md` = 284 lines; delta = 0 (0.0%). Byte-identical (`diff` clean).
- **Changes:** none — zero edits applied.
- **Per-edit pre-edit search log:** no edits were committed, so no (a)/(b)/(c) entries exist. For completeness, the candidate-edit searches that were run and then rejected as unnecessary:
  - Subject "barista half-open overlap" — enumerated `app.py` overlap sites: `barista_double_booked` (app.py:458-469), the accept endpoint's call site (app.py:1509-1510), and `assignment_duration`/`barista_committed_hours` (app.py:341-356). All consistent with PRD §3.4 as written → no wording change needed.
  - Subject "server startup / dependency check" — grep of PRD for `start.sh|startup|pip|flask|boot|install` found only §2.5's logical-clock sentence, which the start.sh change does not touch (app.py unmodified; clock constant lives in app logic) → no wording change needed.

**Output file:** `workspace/PRD_FINALIZED.md` (byte-identical copy of `PRD.md`).

## Step 9: Complete PRD — 2026-08-10T13:55:49.607Z

Done. `workspace/PRD_COMPLETED.md` written (copied from PRD_FINALIZED.md, which was byte-identical to PRD.md, then edited in place only).

**Source vs output:** PRD_FINALIZED.md 284 lines / 46,169 chars → PRD_COMPLETED.md 286 lines / 51,035 chars (+2 lines, +4,866 chars). All changes are in-paragraph inserts/revisions except one new paragraph in §2.1; no new sections.

**Counts:** 14 ambiguity-pins, 6 mismatch-revisions (20 changes total).

**Change log** (impl references are lines in `workspace/implementation/app.py`):

- §2.1 — insert — ambiguity — pinned exact ownership-enforcement surface: Client booking mutations + child-collection lists + forced own-scope bookings list; Barista ownership only on accept/decline/withdraw; single-resource fetches and per-barista assignment list unscoped (app.py:573-575, 1015, 1064-1066, 1486-1488; absence of checks at 654-659, 748-757, 1074-1079, 1478-1483, 1697-1702)
- §2.3 — insert — ambiguity — out-of-range/malformed `limit`/`offset` rejected `ERR_VALIDATION` 400 (never clamped); sort ties broken by insertion order (app.py:268-289, 294)
- §2.4 — insert — ambiguity — `version` starts at 1 on creation (app.py:309)
- §2.5 — revise — mismatch — "ISO-week hour accounting" → "weekly hour-cap accounting" (impl has no ISO-week scoping; app.py:350-355); insert — ambiguity — clock is set to the supplied instant with no forward-only constraint, and automatic transitions fire only at clock-set time, never lazily on other requests (app.py:615-623)
- §2.9 — revise — mismatch — liveness list now includes a booking amendment (impl enforces ACTIVE on merged package/cart/zone at amend; app.py:1333-1335)
- §2.10 — insert — ambiguity — `ERR_VALIDATION` also covers undeclared fields; structural validation sits after path-id existence and before body-FK existence; ownership checks apply once the identifiers they compare against resolve (app.py:182-192, 1009-1016, 1087-1091)
- §3.1 — revise — mismatch — `committed_hours_this_week` sums `duration_hours` over ALL ACCEPTED/CONFIRMED assignments regardless of week (no ISO-week filter; app.py:350-355)
- §3.1 — insert — ambiguity — uniqueness of codes/emails, the illustrative code sets (LATTE_ART…, ZONE-1..3, T1..T3), and Package cross-field zero conventions are declared conventions, not server-enforced (app.py:629-640, 665-682, 763-783, 811-826, 860-876, 901-914, 951-970)
- §3.2 — insert — ambiguity — `distance_km` must be a non-negative integer, else `ERR_VALIDATION` (app.py:1006)
- §3.2 — insert — ambiguity — add-on attach refreshes `updated_at` without incrementing the booking's `version`; duplicate attaches of the same add-on are permitted (app.py:1095-1100)
- §3.2 — insert — ambiguity — offers allowed only while booking is QUOTE/PENDING_DEPOSIT/CONFIRMED (`ERR_INVALID_STATE`); barista status not inspected at offer time; primary uniqueness counts only non-terminal primaries and a second live primary yields `ERR_VALIDATION` 400 (app.py:1122-1129)
- §3.4 — insert — ambiguity — booking-driven assignment cascades (confirm/cancel/amend) increment each affected assignment's `version` (app.py:585-588, 1354-1358, 1412-1415)
- §3.4 — insert — ambiguity — resolve increments the assignment's `version` always; NO_SHOW also increments the barista's `version`, attended COMPLETED does not (app.py:1577-1579)
- §3.5 — revise — mismatch — submission liveness covers package, cart, travel zone, every attached add-on, and items behind RESERVED/COMMITTED reservations (not just package+cart; app.py:1204-1215)
- §3.5 — insert — ambiguity — zone minimum is evaluated against the subtotal freshly recomputed within the submission request, before the stale-version checks (app.py:1236-1237 → 423-425)
- §3.5 — insert — ambiguity — with no live primary assignment, `expected_primary_barista_version` is required but unchecked and no barista version increments on success (app.py:1241-1247, 1258-1259)
- §3.5 — insert — ambiguity — reopen leaves quoted figures and `deposit_due_cents` intact (only variant pins cleared; app.py:1275-1278)
- §3.6 — insert — ambiguity — idempotency runs before amount discipline; replay against a still-PENDING payment with same payload returns the existing row; FAILED keys retryable with any payload; conflict applies to PENDING/SUCCEEDED only; REFUND amount check applies only after a cancellation has priced a refund; system-created payments carry server-generated idempotency keys (app.py:1652-1675, 595-600, 1444-1445, 1470-1471)
- §3.6 — insert — ambiguity — failed BALANCE/REFUND settlement gates rejected `ERR_INVALID_STATE` 409 (app.py:1717-1722)
- §3.6 — insert — ambiguity — automatic CONFIRMED→IN_PROGRESS increments the booking's `version` (app.py:606-609)
- §3.7 — revise — mismatch — completion no longer transitions reservations: they remain COMMITTED until record-consumption moves each to PARTIALLY_CONSUMED (app.py:1466-1472 vs old PRD line 175); insert — ambiguity — completion before `event_end` rejected `ERR_INVALID_STATE` 409 (app.py:1460-1461)
- §3.8 — revise — mismatch — every accepted amendment rolls back to QUOTE regardless of which fields changed (old prose conditioned rollback on changing package/cart/window/guests/distance/add-ons); merged-field semantics, window-check-then-liveness-then-creation-validations order, variant pins cleared with figures left intact, and both old and new cart versions increment on a cart change (app.py:1312-1346, 1364-1385)
- §3.8 — insert — ambiguity — refund tier selected as first ACTIVE tier in creation order; no matching ACTIVE tier yields a zero refund (app.py:1425-1435)

Notable verified non-changes: pricing/deposit math, buffered cart overlap, half-open barista overlap, OCC guard order, cancellation refund formula (floor-after-halving, 168h threshold), inventory conservation, and the full §4 endpoint/role table all match the implementation exactly as written.
