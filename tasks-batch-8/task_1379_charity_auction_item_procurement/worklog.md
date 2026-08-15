# Worklog — task_1379_charity_auction_item_procurement

## Step 1: Create Task Directory — 2026-08-13T02:29:53.477Z

Task directory `tasks/task_1379_charity_auction_item_procurement/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher (Step 1 treated as DONE per invocation instructions). No index scan performed; no other task_* directory touched. Difficulty target: **harder than Expert** (top-of-Expert band on density/coupling per §0.4 of the scaffold-generator skill).

## Step 2: Generate Scaffold — 2026-08-13T03:43:19.531Z

Scaffold generation complete for `task_1379_charity_auction_item_procurement`. All three artifacts written and lint-clean.

## Output files
- `/home/ubuntu/github/CodingPRD/tasks/task_1379_charity_auction_item_procurement/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1379_charity_auction_item_procurement/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1379_charity_auction_item_procurement/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

## Metrics
- **Entities: 14** (GalaEvent, Donor, Bidder, Solicitation, Item, Valuation, Bundle, Bid, Invoice, Payment, Certificate, BlackoutWindow, Disposition, DonorAcknowledgment) — flat topology, FKs in bodies
- **Endpoints: 58** — exceeds the 30–34 band deliberately: the lint rule (f) forces a reverse-reachability GET for every one of the ~20 declared FKs on top of 33 workflow writes; skill §0.4 marks the ranges as guidelines and the task brief allowed "or beyond"
- **Error codes: 34** (all referenced by ≥1 validation/transition; all triggerable via ≥1 design instance)
- **Calculations: 8** — incl. nested-rounding min-bid (order pinned: bps-half-up → floor → grid-ceiling), tiered min-next-bid (strict `<` tier boundary), AGGREGATE-vs-PRORATA revenue/contribution split (pinned divergence: 50000 vs 50001), as-of-issue vs pinned-at-sale acknowledgment FMV, certificate validity/grace windows
- **State machines: 13** — incl. parallel dims (Invoice payment_status × fulfillment_status), genuine cycles (Solicitation SENT↔REVISED, Disposition DONOR_NOTIFIED→PROPOSED reconsideration, Item rollover CATALOGED→UNSOLD→VALUED), compensation reverts (Bundle SOLD→UNSOLD), bubble-up SETTLED/DISPOSITIONED
- **Concurrency: 4 OCC rules** (gala settings, valuation supersede, min-bid override, bid placement) — all framed as stale-version rejection, no race vocabulary
- **Difficulty instances: 27 = 3 per rule × 9 rules** (Rule 4: close cascade depth 5, refund cascade depth 5, valuation→ack cascade depth 3; Rule 8: point-in-half-open-window on Donor vs half-open intersection on Item vs closed containment-with-grace on Certificate; Rule 9: money cents / aggregate FMV / winner-cardinality)
- **Corner design: 43 active instances + 8 excluded_because stubs** across all nine claim-extraction-guide sections
- **Linter: `VERDICT: clean lint`** — 1289 calls scanned across both design files, 0 violations; endpoint/role/payload/capture/OCC/FK checks all pass. Arithmetic in every numeric assert was pre-executed in Python before pinning.

Notable design decisions: certificates merge redemption+scheduling into one atomic `redeem` (keeps temporal-overlap checks on one endpoint); Payment retained as an entity so `/_payments/simulate` has a first-class settle target; `LOST` bid state was removed after reachability analysis showed strict-greater bidding makes it unreachable (enum closure).

## Step 3: Copy Shared Files — 2026-08-13T03:43:19.531Z

Copied `./INSTRUCTION.md` → `tasks/task_1379_charity_auction_item_procurement/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T03:55:00.000Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1379_charity_auction_item_procurement/workspace/PRD.md`.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1379_charity_auction_item_procurement/workspace/PRD.md` — **346 lines**.

**Section list**:
- §1. Introduction (2 paragraphs: business context + governance/fiscal framing)
- §2. Global Specifications: 2.1 RBAC (7 roles, entity-backed Bidder/Donor vs opaque staff, header names, ownership trio), 2.2 API Response Structure (**verified byte-identical** to the canonical `section-2.2-response-structure.md`), 2.3 Pagination (limit 10/1–100, offset 0, `created_at` ascending), 2.4 Common Resource Properties, 2.5 The Logical Clock (default `2026-08-01T00:00:00Z`, expiry sweep), 2.6 Monetary Precision (integer cents, half-up), 2.7 OCC (all 4 rules), 2.8 Validation Order of Evaluation (21-step ordered cascade), 2.9 Nested Resource Retrieval (left-to-right), 2.10 Cascades and Bubble-Ups
- §3. Business Logic: 3.1 Event Configuration & Advancement, 3.2 Donors & Solicitation Pipeline, 3.3 Item Intake/Valuation/Disclosure Tiers, 3.4 Catalog Assembly (bundles, 3-step min-bid, blackouts), 3.5 Bidder Registration & Bidding Exchange, 3.6 Close Cascade & Revenue–Contribution Split, 3.7 Payments/Refunds/Write-Offs, 3.8 Certificates/Redemption/Fulfillment, 3.9 Dispositions/Acknowledgments/Reconciliation
- §4. Endpoint Definitions — 58-row table, 4 columns only (Method, Path, Description, Authorized Role)
- §5. Error Code Catalogue — 34-row table, 2 columns only, no trigger conditions

**Coverage audit (all three Hard Contracts PASS)**:

```
Field coverage check:
- entities[].fields + endpoint inputs/query/path params: 82 required, 82 present, 0 missing
  (includes up_to_cents/increment_cents tier sub-fields, id/created_at/updated_at/version,
   all 10 event-summary output fields, to_iso8601/current_utc, expected_*_version OCC fields)
Status: PASS

Rule coverage check (manual walk of every scaffold entry):
- validations[] priority: 21 checked, 21 expressed as ordered §2.8 cascade, 0 missing
- concurrency_rules[] OCC: 4 checked, 4 expressed (endpoint + expected_<parent>_version +
  ERR_STALE_VERSION/412 each), stale-view framing only, 0 missing
- state_machines[].transitions: 13 machines (incl. parallel Invoice payment/fulfillment,
  Solicitation revision cycle, Item rollover re-entry, Disposition reconsideration cycle),
  all from/to states, preconditions→error_id, and side effects expressed, 0 missing
- calculations[]: 8 checked, 8 expressed in precise prose with pinned evaluation orders and
  scaffold boundary examples (min-bid bps→floor→grid; strict tier boundary 105000;
  AGGREGATE 50000 vs PRORATA 50001; AS_OF_ISSUE 45000 vs PINNED_AT_SALE 40000;
  disclosure tiers 99999/100000/500000/500001; closed redemption bounds, strict sweep)
- validations[] conditions: all 21 matchable to their error_id in §2/§3 prose; all 34 error
  IDs present in §2/§3 (0 missing)
- endpoints[].side_effects / applies_to: version-increment writes, cascade hops, ownership
  trio, OCC quartet, cooldown create+send scope, catalog-freeze endpoint set — all expressed
- entities[].fields[] structured content: defaults, nullability, initial values, enum sets,
  certificate_code CERT-<8 hex> format — reconstructible from prose
- sibling-branch symmetry: sold/unsold close paths, refund/write-off, three disposition
  decisions, AGGREGATE/PRORATA, AS_OF_ISSUE/PINNED_AT_SALE, PREVIEW/LOCKED — equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 621
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Constraint compliance**: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. PRD.md ends at §5 with no audit footer.

## Step 7: Run Tests and Iterate — 2026-08-13T05:00:00.000Z

- **Iterations run:** 3 sweeps (24 total rounds). Final sweep: all 8 rounds passed 96/96.

- **Tests deleted:** none. Every failing test traced to a verbatim PRD rule; all were fixable as test-artifact or implementation bugs.

- **Fixes applied to `test_suite/`:**
  1. `test_03_valuation_tiers_and_acknowledgments.py::test_self_approve_rejected_sod` — the test did `data, _meta = get_success_data(...)`, but that framework helper returns the data dict only (unpack → ValueError). Switched to `validate_paginated(...)`, matching the rest of the file. Assertion itself (SOD rejection leaves valuation `SUBMITTED`) is PRD-faithful.
  2. `test_05_bidding_exchange.py::_event_open_with_draft_and_published_bundles` — helper returned `bundle_a` as the stale create-response snapshot (pre-attach, pre-publish), so the test asserted `min_bid_cents == 9000` on a snapshot that could never hold the locked value, and its `expected_bundle_version` would have hit `ERR_STALE_VERSION` next. Changed `publish_bundle(bundle_a["id"])` to assign its return (`bundle_a = publish_bundle(...)`), so the snapshot carries the post-publish locked minimum bid and current version per PRD §3.4.
  3. `test_06_close_cascade_and_invoices.py` — added missing `setup_published_bundle` to the `from test_helpers import (...)` list (helper existed and was exported; 3 tests failed with NameError on it).

- **Fixes applied to `implementation/`:**
  1. `routes/bundles.py::create_bundle` — was returning `wf.serialize_bundle(rec)`, which substitutes the computed DRAFT preview into `min_bid_cents` (returned 1000 instead of null). PRD §3.4 states the bundle "starts in `DRAFT` with … `min_bid_cents` null" and §2.2 returns the created resource object; the preview variant applies to reads (GET), which `serialize_bundle` still handles. Create now returns `mw.serialize(rec)`.
  2. `start.sh` — replaced the two-interpreter boot (`python3 -c "import flask"` preflight + `python3 app.py`) with a single `python3` heredoc that uses `importlib.util.find_spec` for the dependency check and `runpy.run_path("app.py")`. Halves interpreter startups per per-test-server reboot, cutting boot-time contention that surfaced as harness-level "could not be restarted" errors.
  3. `app.py` — added a bind-retry loop around `app.run(...)`: werkzeug 3.1 converts EADDRINUSE into `sys.exit(1)` after printing, so the loop catches both `OSError` and `SystemExit` and retries for ~12s. This absorbs the kill-then-rebind socket-teardown race (and transient port collisions from other benchmark sessions sharing this host) that deterministically surfaced as the "could not be restarted" flake in 7/8 rounds of sweep 2. Verified empirically: server recovers and serves once the port frees.

- **Not a test/implementation bug:** the "API server could not be restarted" errors (test_04 in sweep 1, `test_07::test_payment_exceeds_outstanding_rejected` in sweep 2, same test in 7/7 rounds within a sweep) were runner-level restart-poll timeouts driven by host CPU contention from concurrent benchmark sessions (tasks 1394/1395 running sweeps simultaneously). Fixed via boot hardening (items 2–3 above), not by touching assertions.

## Step 8: Finalize PRD — 2026-08-13T05:10:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1379_charity_auction_item_procurement/workspace/PRD_FINALIZED.md` with exactly one in-place revision.

## Line counts and delta

- `PRD.md`: 346 lines; `PRD_FINALIZED.md`: 346 lines — 0% line-count delta (one existing sentence revised inline; no sections added).

## Changes

- **§3.4 (Catalog Assembly: Bundles, Minimum Bids, and Blackout Windows)** — **revise** — Extended the preview-vs-locked sentence so the DRAFT preview variant is pinned to appear in every representation of a `DRAFT` bundle (single read, event bundle list, attach/detach responses) with the sole exception of the create response, which returns the bundle as stored with `min_bid_cents` null. This pins the choice Step 7 made in `routes/bundles.py:41` (`create_bundle` returns `mw.serialize(rec)`, not `wf.serialize_bundle(rec)`), resolving the ambiguity in "reading it shows the preview variant" that had allowed the original implementation to substitute the computed preview (1000 instead of null) into the 201 create response.

## Items from `<step_7_diff>` with no PRD edit (and why)

- **Test fix 1** (`test_03` unpacking misuse of `get_success_data`): pure fixture bug; no PRD silence.
- **Test fix 2** (`test_05` stale create-snapshot): fixture bug; publish returning the post-publish bundle with locked `min_bid_cents` and bumped `version` was already pinned by §2.2 + §3.4.
- **Test fix 3** (`test_06` missing `setup_published_bundle` import): pure fixture bug.
- **Impl fixes 2–3** (`start.sh` single-interpreter boot, `app.py` bind-retry loop): process-boot/port-binding resilience — infrastructure contract territory (INSTRUCTION.md), not product behavior the PRD describes. No edit.

## Per-edit pre-edit search log

**Edit 1 (§3.4 preview/create-response pin):**
- (a) **Subject:** which `min_bid_cents` representation each bundle-bearing response shows while the bundle is `DRAFT`.
- (b) **Impl paths enumerated and read/grepped:** all `serialize_bundle` and bundle-`mw.serialize` call sites — `routes/bundles.py:41` (create → stored null), `routes/bundles.py:47` (GET single → preview), `routes/bundles.py:72` (attach → preview), `routes/bundles.py:91` (detach → preview), `routes/bundles.py:115` (publish → PUBLISHED, locked stored value), `routes/bundles.py:137` (min-bid patch → PUBLISHED, stored value), `routes/gala_events.py:226` (event bundle list → preview); `services/workflows.py:52-60` (`serialize_bundle` substitutes preview only when `status == "DRAFT"`); `middleware.py:79` (plain field-copy `serialize`). Also grepped all routes for other serializers to confirm no endpoint embeds a bundle object inside another resource (invoices/bids carry `bundle_id` as a scalar FK only).
- (c) **Wording adjustment:** initial draft said the preview applies "on reads (GET)"; widened to "every representation of a `DRAFT` bundle — the single-bundle read, the event's bundle list, and the attach and detach responses alike" because paths 3–4 (attach/detach mutation responses) also show the preview while DRAFT, and "reads (GET)" alone would have mis-described them. The publish/min-bid paths (5–6) needed no mention: they operate on `PUBLISHED` bundles, already excluded by the "while the bundle is in `DRAFT`" qualifier, and the following sentence ("At publish, the locked variant is computed once… and stored") covers them verbatim.

## Step 9: Complete PRD — 2026-08-13T05:20:00.000Z

PRD_COMPLETED.md is written at /home/ubuntu/github/CodingPRD/tasks/task_1379_charity_auction_item_procurement/workspace/PRD_COMPLETED.md.

## Summary

**Source vs output:** PRD_FINALIZED.md 346 lines / 57,084 chars → PRD_COMPLETED.md 346 lines / 59,119 chars (char-delta +2,035; all edits inline, no lines or sections added).

**Counts:** 15 ambiguity-pins, 0 mismatch-revisions. The finalized PRD already pinned every state machine, calculation order, rounding placement, cascade, and error cascade ordering exactly as implemented; the remaining gaps were validation details, response-shape details, tie-breaks, and enum/format casing.

**Changes (all insert/revise-inline, ambiguity):**

- §2.3 — insert — ambiguity — invalid pagination params (non-integer, limit outside 1..100, negative offset) rejected with `ERR_INVALID_REQUEST` 400 — implementation/middleware.py:98-117
- §2.3 — revise — ambiguity — list ordering ties on `created_at` broken by creation (insertion) order — implementation/middleware.py:120-123
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — implementation/middleware.py:58-67
- §2.5 — insert — ambiguity — non-`created_at`/`updated_at` timestamps serialize ISO 8601 UTC, second precision on whole seconds else three fractional digits — implementation/clock.py:28-33, implementation/middleware.py:76-88
- §2.8 step 5 — insert — ambiguity — a required field present but null counts as missing — implementation/middleware.py:135-138
- §3.1 — revise — ambiguity — `gala_date` is `YYYY-MM-DD` form — implementation/middleware.py:186-197
- §3.1 — insert — ambiguity — `bid_increment_tiers` must be non-empty, each tier needs integer `increment_cents`, omitted `up_to_cents` is open-ended — implementation/routes/gala_events.py:36-50
- §3.1 — insert — ambiguity — PATCH fields explicitly null are treated as absent — implementation/routes/gala_events.py:88-100
- §3.3 — insert — ambiguity — re-valuation with no active (non-VOIDED) acknowledgment leaves acknowledgments untouched — implementation/services/workflows.py:200-212
- §3.4 — revise — ambiguity — attach: already-bundled check precedes valued check; cross-event item rejected `ERR_INVALID_REQUEST` (400) — implementation/routes/bundles.py:62-67
- §3.4 — insert — ambiguity — detach: non-member `item_id` rejected `ERR_NOT_FOUND` — implementation/routes/bundles.py:80-81
- §3.5 — insert — ambiguity — setting a bidder's status to its current value rejected `ERR_INVALID_STATE` — implementation/routes/bidders.py:52-53
- §3.5 — revise — ambiguity — `X-User-ID` naming no bidder of the bundle's event (incl. no persisted bidder) rejected `ERR_BIDDER_EVENT_MISMATCH` — implementation/routes/bundles.py:154-156
- §3.6 — revise — ambiguity — close-cascade order: remaining ties after `published_at`/`created_at` broken by insertion order — implementation/services/workflows.py:250
- §3.6 — revise — ambiguity — `certificate_code` is `CERT-` plus eight uppercase hex characters — implementation/services/workflows.py:223-226
- §3.7 — insert — ambiguity — invoice reads/lists expose `amount_paid_cents` as a read-time computed field — implementation/services/workflows.py:63-66
- §3.9 — insert — ambiguity — `target_gala_event_id` with a non-ROLLOVER decision is existence-checked but stored as null — implementation/routes/dispositions.py:41-59

No PRD-vs-implementation mismatches were found; every error cascade order in §2.8, every calculation placement, and every cascade/bubble-up in §3 matched the code as written.

## Step 5: Generate Unit Tests — 2026-08-13T04:42:03.955Z

Generation complete. Final summary:

## What was built

**Stage 1 — `test_helpers/`** (at `/home/ubuntu/github/CodingPRD/tasks/task_1379_charity_auction_item_procurement/test_helpers/`): `types.py` (14 entity TypedDicts + 17 status/role enums), `api_client.py` (62 endpoint methods subclassing `GenericApiClient`), `api_errors.py` (34 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py` (standard event policy, tier floors, clock default), `test_users.py` (5 opaque roles + `make_bidder_headers`/`make_donor_headers` entity-backed builders), `fixtures.py` (tiered composites: `setup_valued_item`, `setup_published_bundle`, `setup_bidding_open_scenario`, `setup_sold_scenario`, `setup_paid_scenario`, `setup_unsold_scenario`, `setup_two_issued_certificates`, OCC-aware `submit_valuation`/`place_bid`), and the `__init__.py` barrel.

**Stage 2 — `test_suite/`**: `conftest.py` + 9 test files, **96 tests**, all collected cleanly by pytest.

## Coverage

- **Queue A (Difficulty): 54 tests** — all 27 instances covered with exactly ≥2 tests each.
- **Queue B (Corner): 42 tests** — 42 of 43 non-stub instances covered with ≥1 test each; all 8 `excluded_because:` stubs left untranslated (their `difficulty_instance` cross-references all resolve).

## Instances skipped (PRD-first two-condition filter)

- `Corner/entities/bidder_create_system_field_input_ignored` — fails condition 2 (unique derivability). The instance asserts a client-supplied `status: "SUSPENDED"` on `POST /bidders` is ignored and the bidder is created `REGISTERED`. PRD §3.5 states "New bidders start `REGISTERED`", but no PRD sentence states how the server treats an unexpected client-supplied system field in a create payload; §2.8 step 5 covers only "required fields are present, types and enum values are valid". A faithful PRD-only implementer could either ignore the extra field or reject the request as malformed, so the asserted 201 outcome is not uniquely derived. Gap left as a gap — no weakened or placeholder test emitted.

## Stage-2 tag audit result

Pass. All 96 test docstrings carry exactly one `Design:` line as their final line; every tag resolves verbatim to a `name:` in the cited index (27 Difficulty + 42 Corner); no tag points at an excluded stub; no dual/untagged tests. Citation sweep: every docstring's quoted PRD fragment (≥8 words) survives a literal grep of `PRD.md` (0 misses). No `skip`/`skipif`/`xfail` markers, no "scaffold" mentions in generated code.

## Step 6: Generate Implementation — 2026-08-13T04:42:03.955Z

All verification complete. Final summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1379_charity_auction_item_procurement/workspace/implementation/`:

- `start.sh` — guarded pip install (no-op when Flask present) + `exec python3 app.py` foreground launcher
- `requirements.txt` — `Flask>=2.3.0`
- `app.py` — entry point, blueprint registration, envelope-shaped error handlers (404/405/generic), unauthenticated `GET /health`
- `clock.py` — logical clock (default exactly `2026-08-01T00:00:00Z`, never wall-clock for resource stamps)
- `db.py` — 14 empty in-memory stores + insertion sequence (no seeding; verified empty on fresh boot)
- `errors.py` — all 34 catalog error IDs with their exact HTTP statuses
- `response.py` — envelope per scaffold §1.0 (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in meta for arrays)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth for the 7 roles, field/datetime/enum validators, pagination (limit 1–100, offset ≥ 0), serialization (3-fractional-digit `created_at`/`updated_at`, second-precision domain timestamps)
- `services/calc.py` — disclosure tiers (boundary-exact), minimum-bid pinned order (bps half-up → floor → ceil-to-grid), tiered min-next-bid (strict `<` boundary), AGGREGATE + PRORATA split, calendar-month addition
- `services/workflows.py` — close cascade (published_at ASC), PAID cascade (cert issuance window), refund/write-off compensation cascades, cert expiry sweep (strict `>`, equality survives), acknowledgment create/refresh/void+recreate (AS_OF_ISSUE), disposition execution (RETURN/ROLLOVER/DISCARD) and bundle bubble-ups (SETTLED / DISPOSITIONED)
- `routes/` — 11 modules covering all resource groups

## Endpoint count

**58** — matches the scaffold §1.5 table exactly, including the two test-driving endpoints (`/_payments/simulate`, `/_clock/set_current_utc`).

## Clean-boot smoke test result

Passed. From a fresh process: `bash start.sh` binds `0.0.0.0:$PORT` (verified via `ss`), runs foreground via `exec` (process is `python3 app.py`), `GET /health` returns 200 within ~2.5s, a second consecutive fresh boot also returns 200 with an empty store (no seeding), and functional calls work.

Beyond boot checks, I ran three end-to-end suites (each on a fresh boot, all passing) covering: the full happy path from event creation through reconciliation; the documented PRORATA divergence (FMVs 33333/33333/33334 at 150000 → aggregate 50000, prorata 50001); quid-pro-quo boundary (bid == FMV → contribution 0); disclosure-tier boundaries (99999/100000/500000/500001); cooldown half-open window with clock advancement; SoD and all four OCC rules (412); refund and write-off cascades (payments→REFUNDED, cert/bid voided, bundle/items re-opened, dispositions created); rollover with ack void+recreate under the target event; certificate expiry sweep with closed-bound semantics and redemption exactly at `expires_at`; blackout half-open adjacency; ack threshold inclusive `>=`; RBAC/ownership (403s); and pagination meta. Two spec-ambiguity judgment calls: cross-event attach returns `ERR_INVALID_REQUEST` (no error ID exists in the catalog for it), and `amount_paid_cents` computes as the SUCCEEDED sum, which satisfies the PRD's stated conservation law (refund recomputes to zero) that the literal scaffold formula contradicts.
