# Worklog — task_1676_municipal_lost_found_property_management

## Step 1: Create Task Directory — 2026-08-14T06:41:00.000Z

Directory pre-assigned by pipeline launcher: tasks/task_1676_municipal_lost_found_property_management/ with workspace/ subdirectory. Treated as DONE per launcher instructions.

## Step 3: Copy Shared Files — 2026-08-14T06:44:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1676_municipal_lost_found_property_management/workspace/INSTRUCTION.md.

## Step 2: Generate Scaffold — 2026-08-14T07:26:00.000Z

Scaffold generation complete with a clean lint verdict. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_1676_municipal_lost_found_property_management/`.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (561 setup/trigger calls scanned across both design files.)

**Counts**

| Artifact | Count |
|---|---|
| Entities | 13 (Program, RetentionPolicy, StorageLocation, Venue, Claimant, Item, Claim, Inquiry, AuctionEvent, AuctionLot, LotItem, ReferralCase, ReleaseRecord) |
| State machines | 6 (Item 13-state branching with LE-custody cycle; Claim cyclic via INFO_REQUESTED→SUBMITTED; ReferralCase, Inquiry, AuctionEvent, AuctionLot) |
| Concurrency rules (OCC) | 3 (claim-create-stale-item, lot-add-item-stale-lot, policy-create-stale-program) |
| Calculations | 8 (value tier, retention deadline dual-variant, proof score, lot min-bid rounding, occupancy, inquiry SLA dual-variant, auction settlement with pinned eval order, unsold escalation) |
| Validations | 26 (ordered priorities 1–26, auth → existence → state/OCC → safety → constraint → temporal → referential → fiscal) |
| Endpoints | 66 (incl. `/_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z and `/_sweeps/retention`) |
| Errors | 28 |
| Roles | 9 (segregation_of_duties model; Claimant entity-backed, others opaque) |
| Difficulty instances (§1.8) | 19 — all 9 rules ≥2; combinatorial_formula has 3 covering modes (a), (b), (c) |
| Corner instances (§1.9) | 66 (58 with full test recipes, 8 `excluded_because` stubs citing difficulty instances) |

**Maximum-depth design choices**
- Dual-variant calcs in different domains: retention deadline (Item, TRANSIT hour-precise vs FACILITY calendar-day) and inquiry SLA (Inquiry, 24h vs 72h).
- All three combinatorial modes: tier-conditional weighted proof score (a), per-item round-then-sum lot minimum bid pinned against sum-then-round (b), and settlement commission-tier keyed on gross computed before commissions (circular-looking, order pinned) — with precomputed literal asserts (e.g., min bid 1002 for two 5005-cent items; settlement gross 1100000 → commission 88000 → net 1012000).
- Two depth-3 transitive cascades from different triggers (evidence conversion → item → claims; claim approval → item → competing claims auto-REJECTED with ITEM_AWARDED).
- Priority-pair conflicts on distinct category pairs (state vs business_safety on disposed-release; business_referential vs business_fiscal on lot add).
- Boundary checks on distinct metrics/endpoints (value 100000/99999 tier boundary on POST /items; exact-deadline sweep equality on POST /_sweeps/retention).
- Temporal overlap with differing interval semantics (venue half-open adjacency vs storage aggregate-capacity with state-filtered occupation set).
- Compensating invariants over different conserved quantities (total occupied slots across move round-trip; auction-pool cardinality + minimum bid across lot add/remove).
- Computed-field chains: declared_value → value_tier → retention_policy → retention_deadline; verify-id recomputing open claims' proof_score; occupancy recomputed on every status hop.

Fixes applied during lint iteration: quoted bracketed `grounds` refs and list-indexed capture JSONPaths for YAML validity, set `api_prefix: ""` so the lint's collection-segment derivation matches absolute paths, and added five single-resource GETs (`/retention-policies/{id}`, `/venues/{id}`, `/inquiries/{id}`, `/lot-items/{id}`, `/release-records/{id}`) to satisfy FK reverse-reachability.

## Step 4: Generate PRD — 2026-08-14T07:45:00.000Z

PRD generation is complete and all three Hard Contracts pass. Final summary:

## Output

- **File:** `/home/ubuntu/github/CodingPRD/tasks/task_1676_municipal_lost_found_property_management/workspace/PRD.md`
- **Line count:** 350 lines
- **Withheld files:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, grepped, or referenced at any point.

## Section list

- **§1. Introduction** — 2 paragraphs, business-context angle (manual lost-and-found pain points → unified city/transit operation)
- **§2. Global Specifications & System-Wide Principles**
  - 2.1 User and Role-Based Access Control (all 9 roles, per-role `identity:` translations — `Claimant` entity-backed, all others opaque)
  - 2.2 API Response Structure (**byte-identical verbatim block**, diff-verified against `section-2.2-response-structure.md`)
  - 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields)
  - 2.4 Common Resource Properties (`id`/`created_at`/`updated_at`/`version`; explicit absence of `updated_at` and `version` on LotItem and ReleaseRecord)
  - 2.5 The Logical Clock and Time-Gated Rules (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`)
  - 2.6 Optimistic Concurrency Control (all 3 OCC rules with endpoint framing, occ field, error id, 412)
  - 2.7 Validation Order and Error Precedence (all 26 validations in a single deterministic global order)
  - 2.8 Nested Resource Retrieval and Referential Existence (left-to-right path resolution; body FK existence)
  - 2.9 Storage Occupancy Accounting (7-state occupying set, `IN_LE_CUSTODY` + terminal states free slots, capacity rule)
  - 2.10 Monetary Values and Rounding Discipline (integer cents, per-item/per-lot round-half-up before summation, pinned order)
- **§3. Business Logic & Workflows** (8 subsections): 3.1 Programs/Policies/Storage/Venues · 3.2 Intake & Cataloguing · 3.3 Public Portal & Inquiries · 3.4 Claims & Examination · 3.5 Release & Handover · 3.6 Law-Enforcement Referrals & Evidence · 3.7 Retention Expiry, Sweep & Disposal · 3.8 Auctions: Events, Lots, Sales, Settlement
- **§4. Endpoint Definitions** — 66-row table, 4 columns only (Method, Path, Description, Authorized Role(s)); "All staff" shorthand defined in the preamble as the exact 7-role staff set
- **§5. Error Code Catalogue** — 28-row table, 2 columns only (Error ID, HTTP Status Code)

## Hard Contract reports

```
Field coverage check (Contract 1):
- entities[].fields: 69 required, 69 present, 0 missing
- endpoints[].request_body/input: 56 required, 56 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
- endpoints[].query_params: 18 required, 18 present, 0 missing
Status: PASS
```

```
Rule coverage check (Contract 2):
- validations[] with priority: 26 checked, 26 expressed (global order in §2.7 + per-endpoint orderings in §3: intake chain, publish, claim filing, approve, move, release, dispose, add-item, finalize-sale, event create, settle), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write endpoint + expected_<parent>_version + exact error_id + 412 each named), 0 missing
- state_machines[].transitions: 35 checked (Item 19, Claim 15... across Item/Claim/ReferralCase/Inquiry/AuctionEvent/AuctionLot), all from→to pairs, preconditions, error_ids and side_effects expressed, 0 missing
- calculations[]: 8 checked (item_value_tier, retention_deadline w/ TRANSIT hour-precise vs FACILITY calendar-day variants, claim_proof_score weights 30/30/15/15/10 + thresholds 40/60/80+id_verified, lot_minimum_bid pinned per-item rounding, storage_occupancy set, inquiry_sla_deadline 24h/72h, auction_settlement pinned gross→tier→per-lot-commission→net order, unsold_escalation at 2), 0 missing
- validations[] conditions: 26 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (supersession, STAY/restore cascades, ITEM_AWARDED/ITEM_EVIDENCE auto-rejections, claim-create bumps Item.version, event-cancel vs close-unsold unsold_count asymmetry), 0 missing
- entities[].fields[] structured content: defaults/initials/sources reconstructible (active=true, id_verified=false, unsold_count=0, minimum_bid_cents=0, null defaults, computed-vs-input, ignored client value_tier), 0 missing
- sibling-branch symmetry: STORED/LISTED referral branches, AUCTION vs DESTRUCTION/DONATION sweep branches, DESTRUCTION→DISPOSED vs DONATION→DONATED, 3-way STAYED restoration, withdraw/close dual-from states, DRAFT/PUBLISHED cancel cascade — all rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check, §3 only (Contract 3):
- backtick tokens scanned: 461
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additionally verified: all 28 error IDs appear in §2/§3 prose (not just §5), all 41 state values and all enum values (`TRANSIT`/`FACILITY`, 10 item categories, `LOW`/`MID`/`HIGH`, `AUCTION`/`DESTRUCTION`/`DONATION`, `BRIEF`/`DETAILED`, `IN_PERSON`/`MAIL`) appear verbatim, and §2.2 is byte-identical to the canonical source block. No pseudocode or operator syntax was carried into prose; every scaffold expression was translated with boundary inclusivity preserved (e.g., "at least 10,000 cents but below 100,000 cents is `MID`", "a count that has reached 2", "ends_at strictly after starts_at", half-open venue-window overlap with adjacency allowed).

## Step 5: Generate Unit Tests — 2026-08-14T08:35:00.000Z

Generation complete. All 96 tests collect cleanly under pytest with no import errors.

**Output locations**
- `test_helpers/` (9 files): `types.py` (13 entity TypedDicts incl. append-only `LotItem`/`ReleaseRecord` without `updated_at`/`version`, 7 status enums, role enum), `api_client.py` (66 endpoint methods subclassing `GenericApiClient`), `api_errors.py` (28 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity structural asserts + `assert_version_bumped_once` + format-agnostic `assert_instant_equals`), `factories.py`, `constants.py` (tier boundaries, proof weights/thresholds, floor/commission rates, SLA hours, `MAX_UNSOLD_CYCLES`, default clock), `test_users.py` (9 roles; `make_claimant_headers(claimant_id)` mandatory builder for the entity-backed Claimant role), `fixtures.py` (composite setups: program+policy+location, stored/eligible items incl. clock-and-sweep, claims under review / approved, referral custody chains, events/lots/published-lots), `__init__.py` barrel.
- `test_suite/`: `conftest.py` + 12 test files grouped by concern.

**Test counts**
- Queue A (Difficulty): **38 tests** — all 19 instances × 2 tests each.
- Queue B (Corner): **58 tests** — all 58 non-stub instances × 1 test each.
- Per file: test_01 programs/policies/storage (5), test_02 intake/tiers (12), test_03 retention/sweeps/disposal (6), test_04 capacity/moves (6), test_05 publish/public portal/inquiries (11), test_06 claims scoring/review (11), test_07 claim OCC/referrals (9), test_08 release/segregation (6), test_09 auction events (6), test_10 lot pricing (9), test_11 lot lifecycle/settlement (10), test_12 auth/RBAC (5).

**Instances skipped**: none — every difficulty instance and every non-stub corner instance passed the PRD-first two-condition filter (the PRD narrates validation order, OCC rules, and all thresholds verbatim, so both priority-conflict instances are legitimately testable). The 8 `excluded_because` stubs were not translated; all 8 stub cross-references resolve to real difficulty instances.

**PRD-fidelity decisions applied**
- Version assertions are relative (`before + 1`) because PRD §2.4 pins "increments by exactly one on every mutation" but never pins an initial value — absolute `version == 1` assertions would fail the two-reader test.
- Timestamp equality uses instant comparison (`datetime`-parsed) since PRD pins the arithmetic but not fractional-digit formatting.
- `claimant_defaults_id_verified_false` asserts only the PRD-stated default (`id_verified` starts false); the recipe's `phone == null` sub-assertion was omitted per the default-value silence pattern (PRD says only "an optional `phone`").
- Second settlement test for `auction_settlement_pinned_evaluation_order` uses hammers 500005/500030 as a per-lot-rounding discriminator (per-lot total 80002 vs. sum-then-round 80003).

**Audits**: Design-tag audit passes (19/19 difficulty ≥2, 58/58 corner ≥1, zero untagged/dual/unknown tags); verbatim-citation sweep passes (every docstring quote has a ≥8-word substring grep-able in PRD.md); no skip/xfail markers; no scaffold references in generated code; `pytest --collect-only` succeeds (96 tests).

## Step 6: Generate Implementation — 2026-08-14T08:47:00.000Z

Implementation complete and verified. All test servers stopped.

### File list — `workspace/implementation/`

- `start.sh` — foreground launcher; guarded `pip install` (no-op once Flask present); `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=2.2,<4`
- `app.py` — Flask entry point, blueprint registration, envelope-wrapped error handlers (404/405/ApiError/unexpected)
- `db.py` — in-memory dict store (13 collections, empty at every boot; no seeding)
- `errors.py` — all 28 catalog error IDs with exact HTTP statuses
- `response.py` — `meta`/`response_type`/`data` envelope; pagination fields `limit`/`offset`/`total_count`/`has_more` in `meta` for lists
- `middleware.py` — `X-User-Role`/`X-User-ID` auth (401 `ERR_UNAUTHENTICATED`, 403 `ERR_FORBIDDEN`); `X-User-ID` optional only for `PublicUser`
- `util.py` — UUID ids, `req_…` request ids, logical clock (default `2026-08-01T00:00:00Z`, drives `created_at`/`updated_at`/`released_at` and all time-gated rules), Decimal HALF_UP rounding
- `validate.py` — shape validation (400), path/body FK resolution (404), pagination parsing
- `services/core.py` — record lifecycle (version starts at 1, +1 per mutation), value tiers, retention deadlines, proof score, occupancy (computed live), lot minimum bid, settlement math
- `routes/` — `clock.py`, `programs.py` (programs + retention policies), `storage.py` (locations + venues), `claimants.py`, `items.py` (incl. `/public/items`), `claims.py`, `referrals.py`, `inquiries.py`, `auctions.py` (events + lots + lot-items), `release_records.py`

### Endpoint count
**66 endpoints** — the complete PRD §4 table (verified against the registered Flask route map). Smoke-verified ~130 assertions across three suites: full lifecycle (intake → publish → claim → approve → release), referrals (stay/pickup/return/evidence), sweeps, disposal, auctions (cap, OCC, SoD, close-unsold escalation, cancel cascade, tiered settlement incl. per-lot HALF_UP rounding), SLA variants, pagination, and error envelopes.

### PRD ambiguities resolved
1. **400 vs 401 precedence** — PRD §2.7 says malformed requests are rejected "before any ordered business check runs"; I evaluate body/query shape (400) before auth (401), per that literal reading.
2. **OCC fields required** — PRD §2.6 calls them "non-optional", so a missing `expected_*_version` → 400 `ERR_INVALID_REQUEST` (not a skipped check).
3. **Examiner/claimant ownership vs state order** — §2.7 step 2 (forbidden) precedes step 6 (state), and §3.4 confirms this explicitly for approve ("authorization and examiner-ownership first, then state admissibility"); I applied the same order to `request-info`/`reject`/`resubmit`/`withdraw` (ownership 403 before state 409), overriding the scaffold's per-transition listing order.
4. **`api_request_timestamp` and `released_at` source/format** — §2.5 says the logical clock drives "every server-stamped timestamp", so both use the logical clock; formatted with 3 fractional digits like `created_at`. Deadlines (`retention_deadline`, `sla_deadline`) use second precision per §1.3.
5. **Dispose `method=AUCTION`** — accepted as well-formed (the disposal-method vocabulary includes AUCTION), then fails with 422 `ERR_DISPOSAL_METHOD_MISMATCH` since `pending_disposal_method` is only ever DESTRUCTION/DONATION.
6. **Sweep policy lookup** — uses the item's intake-resolved `retention_policy_id` (even if since superseded), per scaffold's `item.retention_policy.disposal_method`.
7. **Pagination out of range** (`limit` <1 or >100, `offset` <0, non-integer) → 400 `ERR_INVALID_REQUEST`, treating declared min/max as validation rules.
8. **Same-location move capacity** — the item's own occupied slot is netted out so a same-location move on a full location doesn't falsely trip `ERR_STORAGE_CAPACITY_EXCEEDED`.
9. **`info_request_text`** — persisted and serialized on the claim (default null) since the state machine says request-info "stores info_request_text" even though the entity table omits it.
10. **Clock regression** — not forbidden by the PRD, so `set_current_utc` accepts any valid ISO instant.
11. **Public `keyword` filter** — case-insensitive substring match on `description` (the only public searchable text field named in the projection).

## Step 7: Run Tests and Iterate — 2026-08-14T09:10:00.000Z

All 8 rounds are clean (96/96 each). The exit condition is met.

---

**Iterations run:** 3 sweeps (baseline → fixture fixes → transport fix), plus one single-round validation between iterations 1 and 2.

**Tests deleted:** None. Every failing assertion traced to PRD-verbatim rules; all failures were test-layer bugs, not coverage/derivability problems.

**Fixes applied to `test_helpers/`** (all in `/home/ubuntu/github/CodingPRD/tasks/task_1676_municipal_lost_found_property_management/test_helpers/`):

1. `fixtures.py` — `setup_auction_eligible_item`, `setup_approved_claim`, `setup_lot_with_eligible_item`, `setup_published_lot_with_item`, `setup_item_in_le_custody`: duplicate-keyword `TypeError` from `SimpleNamespace(**vars(ctx), item=...)` / `claim=...` / `lot=...` where the spread namespace already carried that key. Rewrote as `SimpleNamespace(**{**vars(ctx), "item": item})` merge form. This was the entire 21-test deterministic failure block in iteration 1 (test_08 ×2, test_09 ×2, test_10 ×8, test_11 ×9). Two of these (`setup_published_lot_with_item`, `setup_item_in_le_custody`) were latent — masked by the upstream collision.
2. `fixtures.py` — `setup_auction_eligible_item` + `setup_stored_item`: added `description` kwarg threaded through to `create_item` (tests in test_10/test_11 passed `description="charger A"` etc.; previously `TypeError: unexpected keyword argument`).
3. `api_client.py` — `ApiClient.__init__` now sets `self.session.headers["Connection"] = "close"`. Root cause of iteration-2 flakiness: the session-scoped `requests.Session` pools keep-alive connections, and the runner restarts the server on the *same port* before every test; a pooled connection to the previous (SIGTERM/SIGKILLed) server intermittently produced `ConnectionResetError(104)` on reuse (3 failures of `test_lot_add_rejection_leaves_lot_composition_unchanged` across rounds 1/4/5, near-identical sibling tests green — a transport-layer signal, no HTTP response or PRD rule implicated). Fresh TCP per request eliminates the stale-connection window.

**Fixes applied to `test_suite/`:** None.

**Fixes applied to `implementation/`:** None. The implementation was PRD-faithful throughout; no endpoint, check, or field was added, removed, or weakened.

**Final state:** 8/8 rounds × 96/96 tests passed under `--isolation per-test-server`.

## Step 8: Finalize PRD — 2026-08-14T09:25:00.000Z

Task complete. `PRD_FINALIZED.md` exists at `workspace/PRD_FINALIZED.md` as a byte-identical copy of `PRD.md` — the pure-fixture-bug verdict with zero edits, which the task statement explicitly recognizes as a legitimate outcome.

**Line counts / delta:** PRD.md = 350 lines; PRD_FINALIZED.md = 350 lines; 0% delta (files identical, verified via `diff -q`).

**Changes:** None.

**Per-item evaluation of `<step_7_diff>` (all three items traced to implementation, none revealed PRD silence or PRD/impl mismatch):**

1. **`fixtures.py` SimpleNamespace duplicate-key `TypeError`** (`setup_auction_eligible_item`, `setup_approved_claim`, `setup_lot_with_eligible_item`, `setup_published_lot_with_item`, `setup_item_in_le_custody`) — Pure Python fixture mechanics: `SimpleNamespace(**vars(ctx), item=...)` collided when the spread namespace already carried the key. No endpoint, field, or behavioral rule is implicated; the implementation was untouched and no PRD sentence describes fixture-namespace construction. No edit.

2. **`fixtures.py` `description` kwarg passthrough in `setup_auction_eligible_item` + `setup_stored_item`** — Verified this is *not* a PRD silence: PRD line 170 already pins `description` as a required intake field ("a public-safe `description`"), and PRD line 186 pins it in the public projection. The implementation matches: `implementation/routes/items.py:36` enforces it via `req_str(body, "description")`, stores it (line 71), and projects it (line 145). The failing tests used `description="charger A"/"item B"` purely as distinguishing labels in lot-composition assertions — the fixture helpers simply failed to forward the kwarg. PRD already determines this behavior; prose kept verbatim. No edit.

3. **`api_client.py` `Connection: close` header** — HTTP transport-layer fix in the test *client* (session-scoped `requests.Session` keep-alive pool vs. the runner's per-test server restart on the same port). The PRD is an API-behavior spec; TCP connection reuse is not a behavioral choice the implementation makes at the PRD level, and the implementation itself was unchanged. No edit.

**Per-edit pre-edit search log:** No edits were committed, so no pre-edit searches were triggered. For completeness, the read/grep evidence gathered during evaluation: PRD.md grepped for `description` (lines 170, 186, 196, 198); `test_helpers/factories.py` `create_item_payload` (lines 59-70); `test_helpers/fixtures.py` `create_item` (lines 143-154) and `setup_stored_item` (line 166+); `implementation/routes/items.py` description touchpoints (lines 36, 71, 140, 145); test-suite call sites of the `description` kwarg in test_10/test_11.

**Conclusion:** Step 7 recorded zero implementation fixes and zero test-suite fixes; all three fixes were test-infrastructure bugs (kwargs collision, kwarg passthrough, TCP keep-alive). The implementation was PRD-faithful and the PRD already uniquely determines every behavior these fixes touched, so a fresh implementer reading `PRD.md` (equivalently `PRD_FINALIZED.md`) is already fully constrained at every site Step 7 exercised.

## Step 9: Complete PRD — 2026-08-14T09:45:00.000Z

PRD_COMPLETED.md is complete. Final report:

**Source vs output**: `workspace/PRD_FINALIZED.md` (350 lines, 48,147 chars) → `workspace/PRD_COMPLETED.md` (351 lines, 50,018 chars); char delta **+1,866**.

**Counts**: 14 ambiguity-pins, **0 mismatch-revisions** — every implementation behavior traced to PRD prose was either already uniquely pinned or silent; no passage contradicted the implementation. Three of the 11 pre-recorded resolutions (400-before-401, missing `expected_*_version` → 400, ownership-403 before state-409 on claim actions) were verified as already pinned by §2.7/§2.6 and required no edit.

Changes (all inline; no new sections):

- §2.2 — insert — ambiguity — client-supplied datetimes (`found_at`, `starts_at`, `ends_at`) and clock-response `current_utc` are echoed normalized to UTC: whole-second values at second precision, fractional values with three fractional digits — implementation/util.py:44-49, routes/items.py:72, routes/auctions.py:64-65, routes/clock.py:22
- §2.3 — insert — ambiguity — non-integer/negative `offset`, non-integer `limit` or `limit` outside [1,100], and enum filter values outside the declared set are rejected `ERR_INVALID_REQUEST` (400) — implementation/validate.py:93-139
- §2.3 — insert — ambiguity — list sort is stable: resources created at the same logical-clock instant keep creation order — implementation/validate.py:142-148
- §2.4 — revise — ambiguity — `version` starts at 1 at creation; `updated_at` initially equals `created_at` — implementation/services/core.py:56-65
- §2.5 — revise — ambiguity — logical clock also drives the envelope's `api_request_timestamp` (and `released_at`), each rendered with three fractional digits — implementation/response.py:7-11, util.py:71-73
- §2.5 — revise — ambiguity — clock setting accepts any well-formed instant, including regression (not monotonic) — implementation/util.py:63-65
- §3.2 — insert — ambiguity — same-location move nets the item's own occupied slot out of the destination count before the capacity check — implementation/routes/items.py:198-202
- §3.3 — insert — ambiguity — public `keyword` filter is a case-insensitive substring match on `description` — implementation/routes/items.py:138-140
- §3.3 — insert — ambiguity — `sla_deadline` is an ISO 8601 UTC instant at second precision — implementation/routes/inquiries.py:43, util.py:38-41
- §3.4 — revise — ambiguity — `proof_serial`/`proof_photo`/`proof_receipt` pinned as boolean flags — implementation/routes/claims.py:35-38
- §3.4 — revise — ambiguity — `info_request_text` added to the fields unset at filing (persisted on the claim thereafter) — implementation/routes/claims.py:71
- §3.5 — insert — ambiguity — release answers 200 OK carrying the updated item (not the created release record) — implementation/routes/items.py:259-261
- §3.7 — revise — ambiguity — sweep branches on the policy recorded as `retention_policy_id` at intake, even if since superseded — implementation/routes/clock.py:35-36
- §3.7 — revise — ambiguity — dispose `method` uses the `AUCTION`/`DESTRUCTION`/`DONATION` vocabulary, so `AUCTION` is shape-valid and always lands on `ERR_DISPOSAL_METHOD_MISMATCH` (422) — implementation/routes/items.py:214-221
- §3.8 — revise — ambiguity — `hammer_price_cents` pinned as a non-negative integer (negative → 400 shape error, not 422) — implementation/routes/auctions.py:315

Cross-verified: all 60+ endpoints' role sets, the §5 error catalog, all state machines, calculations (value tiers, retention deadline arithmetic for TRANSIT/FACILITY, proof score weights/thresholds, floor-price and commission rounding order, settlement figures), occupancy accounting, cascade side effects, and check orderings match the PRD as revised.
