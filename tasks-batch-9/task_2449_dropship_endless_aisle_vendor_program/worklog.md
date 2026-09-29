# Worklog — task_2449_dropship_endless_aisle_vendor_program

## Step 1: Create task directory — 2026-09-02T19:47:01.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2449_dropship_endless_aisle_vendor_program` and its `workspace/` subdirectory. Index 2449 was pre-assigned by the invoking pipeline; no index allocation scan was performed (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-02T21:14:29.000Z

All three artifacts are complete and lint-clean in `/home/auto/…` → precisely `/home/ubuntu/github/CodingPRD/tasks/task_2449_dropship_endless_aisle_vendor_program/`:

- `/home/ubuntu/github/CodingPRD/tasks/task_2449_dropship_endless_aisle_vendor_program/SCAFFOLD.yaml` (2,753 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2449_dropship_endless_aisle_vendor_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (3,645 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2449_dropship_endless_aisle_vendor_program/SCAFFOLD_CORNER_DESIGN.yaml` (10,085 lines)

Mandatory lint verdict, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2449_dropship_endless_aisle_vendor_program/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2449_dropship_endless_aisle_vendor_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2449_dropship_endless_aisle_vendor_program/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    44
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     69
  Calls scanned (§1.8+§1.9):  1651

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Scaffold size (§1.0–§1.7): 11 entities / 6 state machines (2 cyclic, 1 parallel-axis order, 1 branching return, 1 compound rollup) / 2 OCC concurrency rules / 11 calculations (3 with variants) / 39 ordered validations / 44 endpoints (all `/dropship`) / 39 error codes (bijective with validations) / 5 roles, `role_model: segregation_of_duties`, `consistency_model: immediate`, `difficulty_level: beyond_expert`.

§1.8 depth probe: 9 rules × 2 differentiated instances = 18 instances, 444 calls. §1.9 breadth probe: 85 instances across the 9 guide sections (entities 13, state machines 17, calculations 16, validations 11, endpoints 7, errors 11, rbac 5, cross-cutting layers 4, consistency 1); 69 carry full `test_recipe`s (1,207 calls) and 16 are `excluded_because` stubs citing a §1.8 instance by name. Verified programmatically: no name collides across the two design files, every stub citation resolves to a real §1.8 instance name, every `${var}` is capture-closed within its own instance, and all 39 error codes carry at least one positive `error_id == ERR_…` assertion.

Design adjudications worth flagging:
- The declared `selector_policy` complexity layer has no row in the claim-extraction guide, so rather than invent a `claim_type` I covered selector determinism through the guide's `topological` (fallback chain walk) and `constraint_propagation` (no-eligible-fallback) calculation rows.
- `ERR_UNAUTHENTICATED` is claimed in the `errors` section (`error_triggerable`, grounded on `VendorUser` being `entity_backed:Vendor` and sending no `X-User-ID`) because Table 7's rows are authorization-only; the `rbac` section stays on `exclusive_operations` / `unauthorized_denial` / `peer_roles` / `shared_operations` / `segregation_of_duties`.
- Segregation of duties is split: §1.8 owns the certify-vs-activate priority conflict, §1.9 owns the fresh evaluate-vs-recorder identity denial.
- Every negative trigger carries `captures: {err: $.data.error_id}` so lint's `is_negative_trigger()` skips role/payload conformance without depending on instance naming.
- No forbidden race vocabulary anywhere; OCC on the parent `version` is the only race mechanism, exercised by both declared rules (`ERR_STALE_ITEM_VERSION` on feed refresh, `ERR_STALE_VENDOR_VERSION` on scorecard publish where suspend+reinstate moves the vendor version out from under the publisher).
- One lint violation was found and fixed (a literal `expected_vendor_version: 1` in the unknown-scorecard 404 instance, now a captured `${vn_ver}`), plus three accuracy fixes: `settlement_balance_cents` (not `settlement_payable_cents`), post-ship `financial_status == CAPTURED`, and the §1.0 density comment corrected to "11 calculations (3 with variants)".
- The hard constraint held: no sibling task directory was listed, globbed, grepped or read; everything derives from the scenario text plus the skill spec and its claim-extraction guide.

## Step 3: Copy shared files — 2026-09-02T21:14:40.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2449_dropship_endless_aisle_vendor_program/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T21:32:10.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2449_dropship_endless_aisle_vendor_program/workspace/PRD.md` — 430 lines, ~14,500 words, ends cleanly at the last row of the §5 table (no sentinel, no mid-sentence truncation, trailing newline present).

**Sections written**
- §1 Introduction
- §2 Global Specifications — 11 domain-derived subsections: 2.1 RBAC, 2.2 API Response Structure (byte-identical to the skill's fixed contract), 2.3 Pagination, 2.4 Common Resource Properties and the Logical Clock, 2.5 Path Resolution and Nested Resource Traversal, 2.6 Validation Precedence, 2.7 Cost Models / Basis Points / Rounding Discipline, 2.8 Cascade Semantics and Version Propagation, 2.9 Optimistic Concurrency on Offers and Vendors, 2.10 Conservation Invariants, 2.11 Segregation of Duties in Onboarding
- §3 Business Logic — 9 lifecycle-grouped subsections: onboarding/integration rounds, coverage & blackouts, offers & cost derivation & substitution chains, inventory feeds & ATP, order capture & quoted promise, transmission/ack/ship-confirm, backorder recovery & fallback walk, returns adjudication & refund waterfall, scorecards/tiers/suspension/reinstatement
- §4 Endpoint Definitions — 44-row table (Method, Path, Description, Authorized Roles)
- §5 Error Code Catalogue — 39-row table

**Hard Contract 1 — Field-Name Coverage: PASS.** Mechanical diff (scaffold-parsed, code fences excluded from the token scan): 132/132 `entities[].fields[].name` present in backticks, 0 missing. All non-entity endpoint inputs also present (`ack_disposition`, `outcome`, `current_utc`, `expected_item_version`, `expected_vendor_version`, `lines`, `limit`, `offset`, plus `promise_divergence_days`, `order_id`, `item_id`, `vendor_id`, `line_id`, `status`, `source`). Enum/state-value sweep: every UPPER_SNAKE enum member and state name present; the only scaffold UPPER tokens absent are prose words (`CASCADE`, `MUST`, `GOTO`, `RBAC`, `ASC`, `EDI`, `YYYY`, …) and internal constant *names* whose values are inlined as literals (e.g. 3× cadence, 1295, 500, 1500 bps, 95/90/80/70, 0.50/0.30/0.20).

**Hard Contract 2 — Rule Coverage: PASS.** All 39 validations appear in §2.6 as a strictly ordered 1–39 list; a rank-by-rank diff against the scaffold confirmed identical order and identical error code at every rank (0 mismatches), with `applies_to` scope stated per rank. Both `concurrency_rules` documented with their exact version field, error and 412. All 35 transitions across the 6 state machines covered, including the `INTEGRATION_TESTING` self-loop with its failed-run precondition, the three `DropshipItem` suppression causes plus both automatic feed-driven legs, the parallel `fulfillment_status` × `financial_status` axes with the compensating `PARTIALLY_REFUNDED → CAPTURED` leg, the cyclic `TRANSMITTED → BACKORDERED → TRANSMITTED`, and `REJECTED` from both `REQUESTED` and `AUTHORIZED`. All 11 calculations have prose formulas including all variant pairs (COMMISSION/WHOLESALE, QUOTED/RECOMPUTED, EVENT_EQUAL/UNIT_WEIGHTED). Sibling-branch symmetry given explicitly for return rejection compensation, suspension vs reinstatement cascades, and auto-suppress vs auto-restore.

**Hard Contract 3 — §3 Path Purity: PASS.** Scanned all backtick spans between `## 3.` and `## 4.`: zero `/`-prefixed tokens, zero bare HTTP methods, zero method+path combos, zero tokens containing `/` at all. §3 refers to operations by role + action verb and by state transition only.

**Coverage notes / decisions**
- Two internal scaffold conflicts resolved in favour of the more specific source: `commission_rate_bps`/`wholesale_discount_bps` documented as 0..5000 (entity constraint) rather than validation #12's 0..10000; pagination `limit` max documented as 100 (`pagination_defaults`) rather than validation #12's 200. Both are worth flagging to whoever owns the scaffold.
- The hard constraint was honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.
- No contract report, audit footer, or generation metadata was written into PRD.md or any sibling file.

**Orchestrator truncation check (per invocation guard):** verified independently — PRD.md is 430 lines, the section list runs §1 → §5 in order, and the tail is the 39th and final complete `| \`ERR_...\` | 4xx |` row of the §5 catalogue. Ends at a real section boundary; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T22:11:49.000Z

The suite is complete and audited.

## Files written

**`test_helpers/`** (9 files, Stage 1, written by me): `__init__.py` (barrel export), `types.py` (5-role enum, 25 status enums, 11 entity TypedDicts), `api_errors.py` (all 39 error ids + HTTP status map registered at import), `constants.py` (thresholds, score weights, tier cutoffs/padding, restock-fee tiers, pagination, clock default), `api_client.py` (`ApiClient` with one method per each of the 44 `/dropship` endpoints), `test_users.py` (5 role header sets + `make_vendor_user_headers(vendor_id)` for the entity-backed VendorUser + the four segregation-of-duties operator ids), `factories.py` (17 payload builders), `assertions.py` (11 per-entity shape assertions + 7 invariant checkers), `fixtures.py` (~680 lines, 6 tiers of setup helpers from `create_draft_vendor` through `setup_backordered_line_with_fallback`).

**`test_suite/`**: `conftest.py` + 17 test modules (`test_01`–`test_09` queue A, `test_10`–`test_17` queue B).

## Test counts

**142 tests total — 68 queue A (Difficulty), 74 queue B (Corner).**

- Queue A: all 18 instances across 9 rules covered, every one with >=3 tests (target was >=2).
- Queue B: all 69 non-stub instances covered (entities 13, state_machines 15, calculations 10, validations 9, endpoints 6, errors 11, rbac 6, cross_cutting 2, consistency_model 2). The 16 `excluded_because:` stubs correctly received no tests.

## Instances skipped

**None.** Every non-stub instance in both indices passed the PRD-first two-condition filter.

## Audit results (script at `/tmp/audit_2449.py`)

- 142/142 tests carry exactly one `Design:` line as the last docstring line; every tag resolves to a real non-stub instance; zero tags point at stubs or nonexistent names.
- All 16 stub `difficulty_instance` cross-references resolve to real §1.8 instances.
- All 142 quoted PRD sentences verified byte-exact against `workspace/PRD.md` (0 misses).
- No `skip`/`skipif`/`xfail` markers anywhere.
- `py_compile` clean on all 26 files; `pytest --collect-only` collects exactly 142 tests with no import errors (AST count matches collection count, so no shadowed duplicates).
- No references to `workspace/implementation/`, SCAFFOLD, or design-index vocabulary in test prose. The implementation directory was never read or written.

## Two Stage 1 defects found and fixed mid-flight

- `types.py` `AckDisposition` read `ACCEPTED`/`BACKORDER`; PRD §3.6 spells them `ACCEPTED`/`BACKORDERED`/`REJECTED`. Fixed the enum and both `acknowledge_payload("BACKORDER")` call sites in `fixtures.py` — without this every backorder-path test would have failed on `ERR_INVALID_REQUEST`.
- `assert_inventory_snapshot` treated `source` as required; PRD line 226 declares it optional. Switched to the optional-enum check.

## Assertions the agents declined to pin (PRD does not uniquely derive them)

Reported rather than guessed: absolute `version` counters wherever an auto-suppress/auto-restore transition may or may not carry its own bump (offer version after a future-dated feed post; vendor version after a probation publish); the clock endpoint's `current_utc` response echo; ship-confirm 200 vs 201; exact fractional-second rendering of `published_at`/`placed_at`; `reported_error_count` persistence.

## Design-index defects the tests corrected toward the PRD

Several recipes carried non-PRD enum spellings, which would have triggered rank-12 `ERR_INVALID_REQUEST` ahead of the intended refusal — substituted with legal values preserving the intent: `HOLIDAY_FREEZE`/`CAPACITY_CRUNCH` -> `HOLIDAY`/`CAPACITY`, `EXPRESS` -> `TWO_DAY`, `OPS_MANUAL` -> `MANUAL_ADJUST`, `NO_RMA_EVIDENCE`/`OUTSIDE_POLICY_ON_INSPECTION` -> `POLICY`, integration status `RECORDED` -> `PENDING`. Three substantive contradictions were resolved in the PRD's favor: a recipe asserting `total_cost_cents` 42498 at order *placement* (§3.5 pins cost only at transmission, so 0/49998 at placement and 42498/7500 after transmit), recipes asserting `restocked_units is null` on a `REQUESTED` return (§3.8 fixes it at 0), and one recipe creating an offer against an `INTEGRATION_TESTING` vendor (§3.3 requires `CERTIFIED` or `ACTIVE`).

## Step 6: Generate implementation — 2026-09-02T22:11:49.000Z

Verification complete. Servers stopped; nothing left listening.

## What was written

`/home/ubuntu/github/CodingPRD/tasks/task_2449_dropship_endless_aisle_vendor_program/workspace/implementation/` — 17 files, 3,258 lines of Python:

- `app.py` (Flask factory, ApiError/HTTPException/Exception handlers, `PORT` env, single-threaded, no reloader), `start.sh` (chmod +x, installs Flask only if missing, `exec python3 app.py`), `requirements.txt`
- Infrastructure: `db.py` (in-memory dicts + logical clock + id/seq/iso helpers), `errors.py` (39 scaffold error ids + 404/405/500), `response.py` (envelope, pagination), `auth.py` (role/scope), `validate.py` (typed field checks, all failures -> `ERR_INVALID_REQUEST`)
- Business logic: `calc.py` (availability/ATP, cost derivation, promise dates, SLA deadlines, cascades, ledger, return routing + financials, retransmit selection, scorecard computation), `serialize.py` (derive-on-read projections)
- Routes: `r_vendors.py` (15), `r_items.py` (8), `r_orders.py` (4), `r_lines.py` (7), `r_returns.py` (6), `r_scorecards.py` (3), `r_clock.py` (1)

**44 endpoints registered** (verified by introspecting `app.url_map`), matching the scaffold's 44. Storage is dicts only — no sqlite, no file I/O, no seeding; every row comes from an endpoint call.

## Verification performed

Three smoke suites (~130 assertions) run against a freshly booted `start.sh` process on clean state. All pass, including every pinned numeric example from the PRD:

- unit cost 1999 @1500 bps -> 1699, x4 -> **6796** (round per unit, then multiply); wholesale 5000 @1000 bps -> 4500
- return refund base 20500 -> fee 2050, freight 1295, **refund 17155**, vendor chargeback 17425; reject-from-AUTHORIZED restores the ledger pair exactly and returns the order to `CAPTURED`
- scorecards on identical data: EVENT_EQUAL cancellation 5000 bps -> **85.00 SILVER**; UNIT_WEIGHTED 9000 bps -> **73.00 WATCH**
- promise example: QUOTED = placed + 8 (lead 3 + transit 4 + padding 1), RECOMPUTED = transmit + 6 (`ceil(40.0/24)=2` + transit 4 + padding 0), divergence 2
- conservation invariants hold: `reserved == lifetime_reserved - released - shipped`; `settlement + chargeback == sum SHIPPED (unit_cost x qty + surcharge)`
- cascades: suspension (rules -> items -> PENDING_TRANSMIT lines -> orders), full-cancellation penalty 500 posted as a pair without bumping vendor `version`, PROBATION publish auto-suspends and blocks reinstate until a non-PROBATION scorecard is published
- snapshot windows (overlap 409, supersede, ZERO_AVAILABILITY auto-suppress/auto-restore, stale gate after a clock jump), blackout conflicts incl. reopen-buffer, retransmit to a same-SKU different-vendor fallback with reservation transfer and zero side effects on `ERR_NO_ELIGIBLE_FALLBACK_VENDOR`, OCC on both `expected_item_version` and `expected_vendor_version`, RBAC 401/403 incl. `ERR_VENDOR_SCOPE_VIOLATION`, pagination bounds, 404/405 routing

## PRD ambiguities resolved

- **Precedence**: ranks 1–39 literally, first failure short-circuits, no mutation on failure. When a rank needs a field that is missing or mistyped, the structural rank-12 `ERR_INVALID_REQUEST` fires instead of the semantic 404.
- **Conflicting ranges**: `commission_rate_bps`/`wholesale_discount_bps` 0..5000 (PRD §2.7 over the scaffold's 0..10000); pagination `limit` max 100 (PRD §2.3 over the scaffold's 1..200).
- **Rank 11 scope**: enforced only on the 7 endpoints its `applies_to` lists, plus `receive`'s `X-User-ID == routed_vendor_id` check; not on snapshot creation or child-list reads, where a false 403 would break happy paths.
- **Derived on read** (never stored): item availability trio, line `ack/ship_sla_breached`/`returned_units`/`line_promise_date`, order fulfillment+financial status, totals, `refunded_cents`, `net_retail_cents`, `retailer_absorbed_cents`, `promise_variant_in_effect`. Only `quoted_promise_date`/`recomputed_promise_date` are stored (max over non-cancelled lines, previous value retained when that set empties).
- **Version policy**: `source: computed` mutations (reservation counters, ledger balances) refresh `updated_at` but never bump `version` — so a settlement credit or chargeback cannot invalidate a pending `expected_vendor_version`. Verified explicitly.
- **Snapshot rank 33**: an ACTIVE open-ended earlier row is treated as virtually closed at the new `effective_from` (adjacency allowed) and then marked SUPERSEDED; governing snapshot = greatest `effective_from`, tie-break `created_at` then insertion seq; age exactly `cadence x 3` counts as FRESH.
- **Blackout rank 34**: overlap conflicts, touching intervals rejected, buffer always taken from the earlier window.
- **Cascade hop 4**: fires only when the order lands fully CANCELLED; amount = 500 x that vendor's CANCELLED_BY_VENDOR lines on the order. Vendor-suspension hop 3 touches only PENDING_TRANSMIT lines, leaving BACKORDERED lines alone.
- **Return edges**: empty routing pool -> RETAILER_DC / null `routed_vendor_id` / RETAILER_RESTOCK with the order absorbing 1295; `receive` ignores any supplied `restocked_units` (0 for DESTROY, else `quantity_returned`).
- **Scorecard empty-population gate**: all-null seeds -> all metrics null, UNRATED, padding 2; any seed present -> asymmetric defaults (on_time 0, cancellation 10000, defect 10000, avg_ship_hours null) and straight to composite; a non-empty population ignores all seeds.
- **Defaults where the spec is silent**: vendor cadence 1440, lead 0, padding 2, ack SLA 24, ship grace 12, buffers 0; item `reverse_freight_owner` RETAILER, `restock_policy` VENDOR_RESTOCK, `defect_window_days` 30, `lead_time_days` <- vendor default; snapshot `source` VENDOR_FEED; `IntegrationTest.reported_error_count` 0; scorecard `metric_variant` EVENT_EQUAL. `feed_sequence` is accepted as input but stored as the server-assigned per-item counter; `ShipmentConfirmation.ship_date` is derived from the clock date; `POST /dropship/orders` returns the order without a nested `lines` array; `IntegrationTest` exposes `created_by_user_id` so the SoD check has a comparand.
- **Creating a test run while the vendor is DRAFT** is allowed (`round_number` 0, since no rank forbids it); its evaluation then fails with `ERR_VENDOR_INVALID_STATE`.

## Step 7: Run tests and iterate — 2026-09-02T22:39:00.000Z

Done — clean 8-round parallel sweep, 142/142 in every round.

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each, `setsid`-launched, ~4.6 min wall per sweep).

- Sweep 1: 12/142 passed in all 8 rounds (130 failures, identical in every round).
- Sweep 2: 140/142 in all 8 rounds.
- Sweep 3: **142/142 in all 8 rounds, 0 failures, no flakiness.**

**Tests deleted:** none. Every failure traced to a test artifact that contradicted PRD prose, or to a field-name mistranslation — all fixable toward greater PRD fidelity. No assertion was weakened, no skip/xfail added.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — `create_integration_test_payload()` emitted `sample_payload_digest="sha256-catalog-digest"`. PRD §3.1 requires "a `sample_payload_digest`, the hex digest of the sample message the vendor submitted, between **8 and 64 hexadecimal characters**"; the literal contains `-` and non-hex letters, so the PRD-faithful implementation correctly answered `ERR_INVALID_REQUEST`. Replaced with `hashlib.sha256(message_type.encode()).hexdigest()`. This single upstream fixture bug was the sole cause of **all 130** sweep-1 failures (1032 of 1040 failure records read `Setup step failed ... sample_payload_digest has an invalid format`), exactly the ">=5 tests sharing one setup error" triage pattern.

**Fixes applied to `test_suite/`:**
- `test_14_corner_endpoints.py::test_order_transmit_is_all_or_nothing_across_its_lines` — asserted `held["fulfillment_status"] == "PENDING_TRANSMIT"` on an **order line**. `fulfillment_status` is the order's derived axis (PRD §3.6); a line's field is `status` ("Each line is created in `status` `PENDING_TRANSMIT`", §3.5). Corrected to `held["status"]`.
- `test_16_corner_rbac.py::test_inventory_feed_is_shared_between_the_vendor_and_the_ops_analyst` — the setup posted the analyst's correction with `effective_from=09:30` while the logical clock still read `09:00`. That post supersedes the prior open-ended snapshot and leaves **no** governing snapshot at the clock, so PRD §3.4's mandatory auto-suppress fires (`ACTIVE -> SUPPRESSED`, `ZERO_AVAILABILITY`), and §3.4 step four then forces `available_units` to 0 — the test's own `available_units == 20` could never hold. Verified against a standalone server both ways. Advanced the clock to `09:30` before the analyst post so the new window is live at posting time; all of the test's original assertions then hold unchanged.

**Fixes applied to `implementation/`:** none. No implementation defect was found — every check the tests tripped on traced to a verbatim PRD sentence, so no PRD-required validation was removed or relaxed.

### Orchestrator verification of the Step 7 claim

The subagent exited claiming green but left **no** `results.*.json` behind — the known failure mode where a Step 7 agent's clean-sweep claim has no durable artifact. Verified two ways rather than taking the claim at face value:

1. Forensic check of the subagent's own `workspace/sweep.log` (preserved as `workspace/sweep.step7.log`): exactly 8 `Results: 142/142 passed, 0 failed, 0 errors, 0 skipped` lines, 0 occurrences of `Terminated` — so the claim was truthful and the sweep was not reaped.
2. Re-ran the full 8-round sweep myself under `setsid` (`workspace/sweep.verify.log`), regenerating the missing deliverables. Result: `results.{1..8}.json` all present with `passed=142 total=142 failed=0 errors=0`; 8 verdict lines in the log; 0 `Terminated`. **ALL GREEN, independently reproduced.**

## Step 8: Finalize PRD — 2026-09-02T22:47:30.000Z

PRD_FINALIZED.md written.

## Line counts
- `PRD.md`: 430 lines / 14487 words
- `PRD_FINALIZED.md`: 430 lines / 14690 words
- Delta: **0% by line** (all three edits are inline insertions inside existing paragraph lines), **+1.40% by word** (+203 words)

## Changes

- **§2.6 rank 33 (Snapshot window disjointness)** — revise — the disjointness rule now excepts the open-ended snapshot the posting supersedes, measuring it as already closed at the new `effective_from` — `implementation/r_items.py:297-313` (the overlap loop's `other_to = effective_from` branch at 305-307).
- **§3.4 (feed message posting)** — insert — two sentences after the supersede sentence: the superseded row is exempt from the overlap test and treated as closed at the new `effective_from`; an `ACTIVE` open-ended window beginning at or after the new `effective_from` is *not* superseded and is overlap-tested as it stands; the supersede write lands only after the overlap test passes — `implementation/r_items.py:300-318`.
- **§3.4 (automatic suppress/restore pair)** — insert — one sentence pinning that both legs are decided on the step-four arithmetic *before* its status gate (trusted on-hand - buffer + grace - reserved, floored at 0), which equals `available_units` for the `ACTIVE` suppress leg but for the restore leg is the would-be-`ACTIVE` figure rather than the 0 a `SUPPRESSED` offer reports — `implementation/r_items.py:336-344` with `implementation/calc.py:198-207` (`atp_raw`).

## Per-edit pre-edit search log

**Edit 1 & 2 (same subject).** (a) Subject: interaction of the snapshot half-open overlap check with the open-ended-supersede rule at feed posting. (b) Paths enumerated: `grep -n "db.snapshots\|SUPERSEDED"` across all of `implementation/` -> writes to `db.snapshots` exist only in `r_items.create_snapshot` (line 332) and the only `status = "SUPERSEDED"` assignment is line 316; read paths are `r_items.list_snapshots` (359), `calc.item_snapshots` (102-104) and `calc.availability` (168-174, `ACTIVE`-only candidates); read `r_items.py:272-347` in full. No other endpoint creates, closes or supersedes snapshots. (c) Adjustment: initially worded as a blanket "an open-ended prior window never conflicts"; widened/re-scoped to distinguish the strictly-earlier case (superseded, exempt) from the at-or-after case (not superseded, tested as it stands), because impl only exempts rows satisfying `other["effective_from"] < effective_from`. Also added the "write lands only once the overlap test has passed" clause so the sentence stays consistent with §2.6's "No row is mutated when a request fails" and with the impl's deferred-write ordering.

**Edit 3.** (a) Subject: which availability figure the post-feed auto-suppress / auto-restore pair is keyed on. (b) Paths enumerated: `grep -n "atp_raw\|available_units\|availability("` across `implementation/` -> `atp_raw` is consumed *only* at `r_items.py:338,342`; every other consumer takes the status-gated `available_units` (`serialize.item:79`, `r_orders.py:81` order placement, `calc.retransmit_target:663`) and in each of those the offer is required to be `ACTIVE` anyway (§2.6 rank 21; retransmit candidate filter `calc.py:648`), so the two figures coincide there. Also checked the other paths that change an offer's status/availability for consistency: `calc.suspension_cascade` hop two (491-494, forces availability to 0 via the status gate), `calc.reinstate_cascade` (522-526, no availability test), `r_items.activate_item` (247-251) and `r_items.suppress_item` (263-266) — none of these consults the pre-gate figure, and my wording confines the claim to the feed-message pair. (c) Adjustment: dropped an earlier phrasing that would have read as "a `SUPPRESSED` offer's `available_units` can be greater than 0", which would have contradicted §3.4 step four and the suspension cascade's "forces `available_units` to 0"; re-scoped to "the step-four arithmetic taken before its status gate", leaving the reported field's value untouched.

## Items that produced no edit
- **`test_helpers/factories.py` digest fixture** — pure fixture bug. PRD §3.1's "between 8 and 64 hexadecimal characters" uniquely determines `validate.HEX_RE` + length bounds + `ERR_INVALID_REQUEST` at rank 12 (`r_vendors.py:241`). No silence, no mismatch.
- **`test_14` `held["fulfillment_status"]` -> `held["status"]`** — pure test bug. `serialize.line` (154-176) carries `status` and no `fulfillment_status`; `fulfillment_status` is the order's derived axis (`serialize.order:139`). PRD §3.5/§3.6 already say exactly this.
- **`test_16` clock advance** — the timing itself is PRD-determined (governing-snapshot selection, mandatory auto-suppress, step-four gate all match impl); only the two latent §3.4 gaps above, which that fix's reasoning turned on, needed pinning.

## Step 9: Complete PRD — 2026-09-02T23:05:20.000Z

`PRD_COMPLETED.md` is complete and intact.

## Summary

**Line counts / char-delta**
- `PRD_FINALIZED.md` — 430 lines, 104,665 chars
- `PRD_COMPLETED.md` — 430 lines, 115,081 chars
- Delta: **+10,416 chars, 0 lines** (40 modified line-pairs; all changes are in-paragraph inserts/revisions, no new sections, no new paragraphs)
- Ends at the complete §5 error catalogue table (final row `| ERR_NO_ELIGIBLE_FALLBACK_VENDOR | 422 |`), not truncated.

**Counts: 5 mismatch-revisions, 39 ambiguity-pins (44 changes total)**

### Mismatch-revisions
- §2.1 — revise — mismatch — deleted the absolute "There is no cross-vendor read path whatsoever" claim; scoping applies only to the §2.6 rank-11 enumeration plus return receipt, so list endpoints and snapshot posting are unscoped — `auth.py:42-59`
- §2.8 — revise — mismatch — version propagation is not universal: reservation-only offer moves and all vendor-ledger postings refresh `updated_at` without bumping `version`; ack bumps only the line; return authorize/reject bump return+order but never the line; receipt bumps only the return — `calc.py:461-472`, `r_orders.py:121`, `r_lines.py:208-213`, `r_returns.py:146-154`
- §3.3 — revise — mismatch — offer restoration gate tests only that `suppression_reason` is not `VENDOR_SUSPENDED`; `MANUAL`, `ZERO_AVAILABILITY` and null all clear it — `r_items.py:223-245`
- §3.4 — revise — mismatch — `feed_sequence` in the body is advisory only; the stored value is a server-minted 1-based per-offer counter — `r_items.py:281,284`
- §3.9 — revise — mismatch — publish evaluates vendor-version before scorecard state (and a missing vendor row also reports `ERR_STALE_VENDOR_VERSION`) — `r_scorecards.py:101-113`

### Ambiguity-pins
- §2.1 — insert — ambiguity — `X-User-ID` absent **or empty string** -> 401 — `auth.py:35-36`
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + 20 uppercase alphanumerics; `api_request_timestamp` is the only value read from the host wall clock, not the logical clock — `response.py:19-28`
- §2.3 — insert — ambiguity — ordering tie-break is insertion order and `id` is never consulted — `db.py:120`
- §2.3 — insert — ambiguity — enum filters are validated (`ERR_INVALID_REQUEST`); identifier/code filters are matched literally, unvalidated — `validate.py:166-197`
- §2.3 — insert — ambiguity — absent **or empty** pagination params fall back to defaults — `response.py:69-89`
- §2.6 r34 — insert — ambiguity — blackout reopen buffer is symmetric in direction — `r_vendors.py:398-405`
- §2.8 — insert — ambiguity — enumerated the derived-on-read order/line fields vs the two stored promise rollups — `calc.py:227-309`, `serialize.py:131-176`
- §2.9 — insert — ambiguity — both `expected_*_version` fields must be integers >= 0 — `r_items.py:282`, `r_scorecards.py:102`
- §3.1 — insert — ambiguity — `inventory_refresh_cadence_minutes` default 1440, `default_lead_time_days` default 0, `promise_padding_days` integer 0–5 — `r_vendors.py:41,44,47`
- §3.1 — insert — ambiguity — integration-round self-transition clears `certified_by_user_id` to null — `r_vendors.py:131-132`
- §3.1 — insert — ambiguity — test-creation payload is exactly `message_type` + `sample_payload_digest`; no vendor-state precondition, so a DRAFT vendor's run freezes at round 0 — `r_vendors.py:240-255`
- §3.1 — insert — ambiguity — omitted `reported_error_count` leaves stored 0; three evaluation preconditions run in written order after body validation, SoD skipped when `created_by_user_id` is null — `r_vendors.py:294-322`
- §3.1 — insert — ambiguity — activation SoD passes unconditionally when `certified_by_user_id` is null; activation clears `suspension_reason` — `r_vendors.py:178,188`
- §3.2 — insert — ambiguity — buffer is read off the earlier window, so a window entirely before an existing ACTIVE one is judged against its own `reopen_buffer_days` — `r_vendors.py:398-405`
- §3.2 — insert — ambiguity — cancelling an already-`CANCELLED` window is a 200 no-op touching neither `updated_at` nor `version` — `r_vendors.py:447-449`
- §3.3 — insert — ambiguity — `vendor_id` must be present and a string before lookup — `r_items.py:61-62`
- §3.3 — insert — ambiguity — `reverse_freight_owner` defaults `RETAILER`, `restock_policy` defaults `VENDOR_RESTOCK` — `r_items.py:76-77`
- §3.3 — insert — ambiguity — amendment bumps version on an empty body; explicit nulls ignored except `fallback_item_id` (clears) and `unit_wholesale_cost_cents` on WHOLESALE (-> `ERR_COST_MODEL_FIELD_MISMATCH`) — `r_items.py:182-213`
- §3.3 — insert — ambiguity — activation's three demands run liveness -> coverage -> wholesale-cost — `r_items.py:223-245`
- §3.4 — insert — ambiguity — `source` defaults `VENDOR_FEED`; snapshot posting carries no vendor-scope comparison — `r_items.py:320,274`
- §3.5 — insert — ambiguity — `lines` must be present and non-empty — `r_orders.py:42-43`
- §3.5 — insert — ambiguity — `line_promise_date` reports RECOMPUTED once derived else QUOTED; rollups recomputed per write and retain their last value when no surviving line carries that variant — `calc.py:346-364`
- §3.5 — insert — ambiguity — promise read returns exactly five fields; divergence is 0 whenever either date is null — `r_orders.py:138-144`, `calc.py:368-370`
- §3.6 — insert — ambiguity — each transmit guard sweeps every pending line before the next; no staleness/availability recheck, no reservation moves; answers 200 with the order — `r_orders.py:157-193`
- §3.6 — insert — ambiguity — ack does scope before body validation, `ack_disposition` before line state, vendor-ACTIVE after line state — `r_lines.py:65-80`
- §3.6 — insert — ambiguity — `shipped_units` mismatch is structural and precedes line state; rank-26 liveness applies — `r_lines.py:100-115`
- §3.6 — insert — ambiguity — ship-confirm answers 201 with the shipment row in `data`, not the line; shipment list takes only pagination — `r_lines.py:120-161`
- §3.7 — insert — ambiguity — chain walk also stops at a pointer naming no offer — `calc.py:630-639`
- §3.7 — insert — ambiguity — retransmit bumps line and order versions but neither offer's — `r_lines.py:206-219`
- §3.8 — insert — ambiguity — `line_id` must be present and a string — `r_returns.py:45-49`
- §3.8 — insert — ambiguity — return-quantity cap counts only AUTHORIZED/RECEIVED returns, so two REQUESTED returns may each claim the whole line — `calc.py:255-260`, `r_returns.py:64`
- §3.8 — insert — ambiguity — authorize order is line-SHIPPED -> return state -> defect window; role list includes `PlatformAdmin` — `r_returns.py:126-141`
- §3.8 — insert — ambiguity — receipt's ownership comparison runs after the return-state check; `restocked_units` must be >= 0 and is otherwise ignored — `r_returns.py:164-179`
- §3.8 — insert — ambiguity — `rejection_reason` required and validated before the return's state — `r_returns.py:190-195`
- §3.9 — insert — ambiguity — seeded `avg_ship_hours` is rounded half up to two decimals — `calc.py:756`
- §3.9 — insert — ambiguity — suspension hop four bumps the order's version once, and only when re-derivation changes the value — `calc.py:506-513`
- §3.9 — insert — ambiguity — reinstatement refusal covers a vendor with no `PUBLISHED` scorecard at all — `r_vendors.py:218-222`
- §3.9 — insert — ambiguity — reinstatement restores `inactivated_by_suspension` rows from whatever status they sit in — `calc.py:517-521`
- §4 — insert — ambiguity — clock endpoint takes required `current_utc`, answers 200, returns `current_utc` alone — `r_clock.py:13-19`
- §5 — insert — ambiguity — framework-level `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 — `app.py:40-52`, `errors.py:43-45`

### Orchestrator verification

`PRD_COMPLETED.md`: 430 lines / 115,081 chars, all five sections present in order (§1 -> §5), 39 `ERR_` rows in the §5 catalogue, tail is the complete final table row. Not truncated.

Staleness check on the green sweep: newest `implementation/` file is `start.sh` @ 21:56:55 and newest test file is `test_16_corner_rbac.py` @ 22:25:57, both older than `results.1.json` @ 22:38:15 — Steps 8 and 9 touched only PRD documents, so the verified 8x142/142 sweep still holds for the final artifacts. No re-run needed.

**Pipeline complete.**
