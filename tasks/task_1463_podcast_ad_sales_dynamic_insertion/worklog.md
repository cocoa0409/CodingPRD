# Worklog — task_1463_podcast_ad_sales_dynamic_insertion

## Step 1: Create Task Directory — 2026-08-13T09:41:00.000Z

Task directory `tasks/task_1463_podcast_ad_sales_dynamic_insertion/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 3: Copy Shared Files — 2026-08-13T09:41:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1463_podcast_ad_sales_dynamic_insertion/workspace/INSTRUCTION.md`. (Done early, while Step 2 scaffold generation runs in background — Step 3 has no dependency on Step 2 output.)

## Step 2: Generate Scaffold — 2026-08-13T10:49:00.000Z

All three scaffold artifacts are generated and lint-clean. Final report:

### Files written

- `tasks/task_1463_podcast_ad_sales_dynamic_insertion/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `tasks/task_1463_podcast_ad_sales_dynamic_insertion/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `tasks/task_1463_podcast_ad_sales_dynamic_insertion/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

(The `worklog.md`/`workspace/` entries in that directory predate this run and were left untouched.)

### Design summary

- **Complexity profile**: quota/allocation (show forecast pool + episode slot capacity) with pricing-engine secondary; layers = optimistic concurrency (OCC on `Show`/`Campaign` PATCH), cascading side effects, dual-variant calculation, scheduled actions via a logical clock (`POST /_clock/set_current_utc`, pinned startup default `2026-08-01T00:00:00Z`). Flat topology (peer entities + FK bodies), cyclic state machines, peer_roles RBAC, immediate consistency.
- **Surface**: 12 entities (Show, Episode, Agency, Advertiser, Campaign, LineItem, AdCopy, Download, Impression, AttributionEvent, Invoice, MakeGood), 44 endpoints (incl. the clock test-driver; all FKs reverse-reachable), 9 calculations, 30 error codes, 6 roles with `identity:` declared (Advertiser/Agency/ShowProducer entity-backed; AdOps/Finance/Ingestion opaque).
- **Key mechanics**: provisional-vs-final download qualification (BOT filter vs HUMAN+window+per-listener-day dedupe), ACTUAL_DELIVERY vs BOOKED_GROSS billing, per-line round-then-sum with position multipliers (800/1000/600 per mille), pinned commission evaluation order (delivered→gross→credit→commission→net), half-open category exclusivity vs aggregate episode slot capacity, make-good offer/accept/decline with campaign reopen and fulfillment threshold.

### Difficulty design (§1.8) — 19 instances, all 9 rules ≥2

Dual-variant (measurement vs billing domains), combinatorial modes (a) tiered forecast, (b) per-line rounding 13≠12, (c) commission order 180/1020 vs 240/960 — all literals precomputed via Python; cyclic AdCopy revision loop and Campaign pause/resume + make-good reopen; depth-3 cascades (advertiser suspend; finalize-measurement); priority conflicts state>fiscal and safety>referential; boundaries (flight end==start adjacency; shortfall 0 vs 1); cross-entity gates (Campaign×AdCopy, Invoice×MakeGood); reserve/release invariants on show impressions and episode slots.

### Corner design (§1.9) — 43 active instances + 3 excluded stubs across all 9 guide sections; every §1.6 error code is triggerable by at least one instance.

### Verification

Replay pass fixed three issues found by hand-replaying chains: a negative-`available_impressions` wording contradiction, forecast-horizon starvation in the make-good reopen chains (reworked clock choreography to 2026-08-25), and missing forecast-pool episodes in three exclusivity setups. Final lint output, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(44 endpoints, 12 entities, 19 §1.8 + 43 §1.9 instances, 675 calls scanned.) Additionally verified: no forbidden concurrency vocabulary, unique instance names across both design files, stub `excluded_because` references resolve, OCC `expected_*_version` always captured from a prior response.

## Step 4: Generate PRD — 2026-08-13T11:02:30.000Z

All checks pass. The PRD is complete at `tasks/task_1463_podcast_ad_sales_dynamic_insertion/workspace/PRD.md` (295 lines).

**What was generated:** A prose PRD for the Podcast Ad Sales & Dynamic Insertion API with:
- §1 Introduction (2 paragraphs, business-context angle)
- §2 with 9 subsections: RBAC with per-role identity semantics, verbatim §2.2 envelope contract, pagination, the logical clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601` setter, recompute side effects), common resource properties (including the explicit `updated_at`/`version` absence for Download/Impression/AttributionEvent), money/rounding discipline (integer cents, round-half-up, per-mille position multipliers, floor forecasts), OCC (both PATCH endpoints, `expected_campaign_version`/`expected_show_version`, `ERR_STALE_VERSION` 412), a 14-step ordered validation pipeline mapping all priorities to error IDs, and the provisional-vs-final measurement principle
- §3 with 7 subsections organized by business process (inventory → buyers/campaigns → creative review → line-item sales gates → insertion/measurement → attribution → billing/make-goods/reconciliation), with all formulas expressed in reconstructible prose (forecast caps 0.95/0.70/0.00 over a 30-day horizon, per-listener-per-UTC-day dedupe, per-line pinned rounding with one-million divisor, pinned commission evaluation order, 30-day inclusive attribution window, make-good fulfillment with tie-fulfills boundary) and cascades fully specified
- §4 endpoint table (44 rows, 4 columns) and §5 error catalogue (30 rows, 2 columns)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs/outputs/query params: 82 required, 82 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 14 checked, 14 expressed in ordered §2.8 prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write op + expected_*_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 30 checked (Show 5, Episode 2, Advertiser 2, Campaign 8, LineItem 5, AdCopy 6, Invoice 4, MakeGood 4 — incl. system transitions), 30 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed in precise prose (floor/round-half-up/inclusive bounds/pinned orders), 0 missing
- validations[] conditions: all matchable to error_ids in §2/§3 narrative; all 30 error IDs mentioned
- endpoints[].side_effects / applies_to: expressed (brand safety at create AND activate, clock-set recompute, invoice auto-MakeGood, selector ranking priority DESC/created_at ASC)
- entities[].fields[] structured content: defaults, ranges, enum sets, immutable billing_model, null-until-measured flags all reconstructible
- sibling-branch symmetry: tier transitions, review outcomes, billing variants, FULFILLED/EXPIRED branches at equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 465
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: no fuzzy/approximating words, no pseudocode operators (`==`, `>=`, `+=`, etc.) outside the verbatim §2.2 JSON block. The two withheld difficulty/corner design files were never opened.

## Step 5: Generate Unit Tests — 2026-08-13T11:52:00.000Z

Generation complete. Summary of what was produced for task_1463_podcast_ad_sales_dynamic_insertion:

### Stage 1 — `test_helpers/` (9 files, import-verified)

- `types.py` — 14 enums + 12 entity TypedDicts; Download/Impression/AttributionEvent correctly modeled as append-only (no `updated_at`/`version`) per PRD §2.5.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (39 methods, including `/_clock/set_current_utc`).
- `api_errors.py` — all 29 PRD §5 error IDs with HTTP statuses, registered via `set_error_http_status_map` (note `ERR_FLIGHT_WINDOW_INVALID: 422`, `ERR_STALE_VERSION: 412`).
- `assertions.py` — per-entity asserts + `assert_invoice_invariants` (net + commission + credit == gross) + `assert_instant_equal` (timezone-safe instant comparison, used for the flight_end +14d assertion so millisecond formatting can't false-fail).
- `factories.py`, `constants.py` (caps 0.95/0.70/0.00, position per-mille 800/1000/600, horizon 30d, attribution window 30d, startup clock 2026-08-01T00:00:00Z).
- `test_users.py` — opaque shared constants for AdOps/Finance/Ingestion; `make_advertiser_headers` / `make_agency_headers` / `make_show_producer_headers` builders for the three entity-backed roles (threaded through every ownership-gated call in fixtures).
- `fixtures.py` — creators/transitions plus composites: `create_and_approve_copy`, `setup_selling_scenario`, `add_line_item`, `publish_episode`/`deliver_downloads`/`finalize_episode_measurement`, `end_campaign`, `invoice_campaign`, and the workhorse `setup_measured_delivery`.
- `__init__.py` barrel export.

### Stage 2 — `test_suite/` (16 test files, 81 tests, all collected by pytest)

- **Queue A (difficulty): 19/19 instances, exactly 2 tests each (38 tests)** across test_01–test_08 (dual-variant qualification/billing, forecast tier recompute, per-line round-then-sum, pinned commission order, ad-copy revision loop, pause/resume + make-good reopen, both cascades, both priority-pair conflicts, both boundaries, both temporal-overlap rules, both cross-entity gates, both compensating invariants).
- **Queue B (corner): 43/43 non-stub instances, 1 test each** across test_09–test_16 (entities 7, state_machines 11, calculations 4, validations 11, endpoints 3, rbac 3, cross_cutting 3, consistency 1). The 3 `excluded_because` stubs in the errors section were not translated; their cross-references were verified to resolve.

### Adjudication notes (PRD-first filter)

- `show_creation_applies_defaults`: dropped the `version == 1` literal — PRD §2.5 says version is "an integer starting at its initial value on creation" without pinning the start value (fails unique derivability); the test asserts integer presence/type instead. All other instance assertions (defaults [], CLEAR, 0/0/0, created_at) are PRD-verbatim covered.
- `episode_creation_applies_defaults`: dropped `measured_download_count == 0` pre-finalize (PRD stores it at finalization; pre-finalize value unspecified) — kept provisional_download_count/slots_in_use == 0 and the forecast recompute.
- `campaign_patch_occ_stale_after_increment`: asserts `version == captured + 1` instead of the literal `== 2`, for the same unspecified-start-value reason.
- Priority-pair instances were kept (not skipped under the validation-priority silence pattern) because PRD §2.8 explicitly enumerates the pipeline order and states "the first failing check wins".

### Verification performed

- All files byte-compile; `pytest --collect-only` collects 81 tests cleanly.
- Tag audit script: every difficulty instance ≥2 tags, every corner non-stub ≥1 tag, zero bogus tags, zero stubs translated.
- Citation sweep: 120 quoted PRD sentences, all survive whitespace-normalized literal grep of PRD.md; every docstring ends with exactly one `Design:` line; no skip/xfail markers anywhere.
- Import audit: every `from test_helpers import ...` name in test_suite resolves to a real export.

Files live under `tasks/task_1463_podcast_ad_sales_dynamic_insertion/test_helpers/` and `.../test_suite/`.

## Step 6: Generate Implementation — 2026-08-13T12:20:00.000Z

All 44 spec endpoints are registered (the 45th is Flask's built-in `/static` route, which conflicts with nothing). Verification is complete — every batch ran clean. (Note: the agent's turn ended twice at intermediate status lines mid-verification; the orchestrator resumed it both times to run the remaining batches. The summary below is its final report.)

### Summary

**Implementation written** to `tasks/task_1463_podcast_ad_sales_dynamic_insertion/workspace/implementation/`:

- `start.sh` — foreground launcher, `exec python3 app.py`, guarded dependency install (`if ! python3 -c "import flask"`), `PORT` env (default 10000), binds `0.0.0.0`
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — entry point, ApiError/404/405/500 handlers, blueprint registration
- `db.py` — in-memory stores (empty at boot, no seeding), logical clock (startup default `2026-08-01T00:00:00Z`, echoes caller's raw timestamp)
- `errors.py` — all 30 error IDs with correct HTTP statuses
- `response.py` — scaffold envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), list pagination in meta (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, 1..100), created_at-ascending sort, `_`-key stripping serializer
- `middleware.py` — `X-User-Role`/`X-User-ID` auth (401/403), Advertiser/Agency/ShowProducer entity-backed scoping (ERR_FORBIDDEN vs ERR_AGENCY_MISMATCH)
- `services.py` — `Changes` unit-of-work (single version bump per changed entity per request), inventory forecast (floor, tier caps 95/70/0, inclusive 30-day horizon), slot occupancy (clock-gated), cascades (advertiser-suspend depth-3, show-suspend with campaign bubble-pause, copy-revocation without bubble-pause), final measurement (HUMAN-only, inclusive window, per-listener-per-UTC-day earliest dedupe), insertion selector (priority DESC, created_at ASC, half-open flight), billing (per-line round-half-up then sum, position multipliers 800/1000/600 per-mille over 1e6), pinned commission order (gross→credit→commission→net), attribution window (inclusive, current flight_end + 30d), make-good fulfillment (>= fulfills), campaign reconcile
- `routes/` — 11 blueprints implementing all 44 endpoints with the PRD §2.8 validation pipeline order (auth → role → ownership → agency-mismatch → existence → OCC → state → brand safety → cross-ref → temporal → structural → inventory → make-good block → field shape)

**Verification** (each batch against a fresh `python3 app.py` boot; final boot via `bash start.sh` itself):

1. **Part 1 (24 checks)** — envelope, defaults, 401/403/404, publish gating, clock set, 422 flight window, agency mismatch, advertiser/agency ownership, campaign OCC 412 + version increment, foreign PATCH 403
2. **Part 2 (deep chains)** — dual-variant measurement (provisional 3 / measured 1), finalize boundary (at-close 409, +1s ok), ACTUAL_DELIVERY 4000 vs BOOKED_GROSS 5000, per-line rounding 6+6+1=13, pinned commission 1600/400/180/1020 with invariant, make-good OFFERED auto-create, issue-block, decline credit recompute, dispute/re-issue frozen, MARK_PAID reconcile. (Two reported failures were wrong literals in my test script — cpm 5000 gives credit 1000/net 3000, and the implementation's values were correct per formula; the pinned-order scenario itself passed at 400/180/1020.)
3. **Part 3 (46 checks)** — advertiser-suspend cascade with no-unwind reinstate, show-suspend cascade + bubble-pause + SUSPENDED→CLEAR rejection + FLAGGED cap 7000, exclusivity adjacency (end==start admitted) vs overlap conflict, same-advertiser overlap allowed, slot capacity 2-fits-3rd-rejected, clock-gated slots_in_use, selector priority/created_at determinism, attribution inclusive boundaries, full campaign report
4. **Part 4** — make-good ACCEPT validation (extension_days 1..30), ENDED→ACTIVE reopen with flight_end +14d, FULFILLED at exact tie, EXPIRED when short, forecast horizon inclusive upper bound, MEASURED-episode exclusion, state-beats-fiscal (ERR_CAMPAIGN_NOT_ACTIVE over ERR_INSUFFICIENT_INVENTORY), safety-beats-referential (ERR_BRAND_SAFETY_CONFLICT over ERR_COPY_CAMPAIGN_MISMATCH), exact-fit inventory equality, TARGET_SCOPE both/neither, format-kind mismatch, HOST_READ_REQUIRES_SHOW
5. **Part 5** — full copy revision loop (submit/rev 1 → changes → resubmit rev 2 → approve → revoke), reviewer scoping (AdOps 403 on host-read, producer 403 on produced-audio/foreign show, owner-only WITHDRAW), revocation cascade releasing pool without campaign bubble-pause, cancel lockdown, no-approved-copy gates, PATCH state/OCC/422/missing-field matrix, show PATCH forecast recompute, zero-delivery invoice + ecpm zero-guard, invoice-before-end, measurement-pending, pagination envelope + bounds + filters, Finance/Advertiser RBAC on downloads/impressions
6. **Part 6** — END-time reconcile with PAID invoice + FULFILLED make-good, clock RBAC/malformed input, download count 1..1000 bounds, listener_key minting (`prefix-i`), array response without pagination meta, all FK 404s, mixed run-of-show + episode targeting, paused-campaign and out-of-flight non-serving

All batches clean: **zero failures**. Store starts empty on every boot; no seeding anywhere.

## Step 7: Test/Fix Iteration Loop — 2026-08-13T12:40:00.000Z

All 8 rounds pass 81/81. The exit condition is met. Cleaning up the stray results files is not required (they're regenerated each sweep); leaving them in place.

---

### Summary

**Iterations run: 2** (initial sweep surfaced 3 deterministic failures; fix sweep clean 8/8).

**Tests deleted: none.** Every failing test traced to a verbatim PRD rule; all fixes landed in `test_helpers/`.

**Fixes applied to `test_helpers/`:**

1. `test_helpers/fixtures.py` — `setup_selling_scenario()` now pins the logical clock to `DEFAULT_CLOCK` (`2026-08-01T00:00:00Z`, the PRD §2.4 startup value) before building entities. Root cause of `test_delivered_exactly_booked_creates_no_makegood` and `test_delivered_one_below_booked_creates_makegood_for_one` (both in `test_06_difficulty_boundary_overlap.py`): `_setup_threshold_pair` builds two full `setup_measured_delivery` scenarios in one server; the first scenario's `finalize_episode_measurement` advances the clock to `2026-09-01T00:00:01Z`, so the second scenario's new episode (`publish_at=2026-08-01`) fell outside the forecast horizon `[now, now+30d]`, the show forecast computed to 0, and line-item activation correctly raised `ERR_INSUFFICIENT_INVENTORY` (HTTP 409). The implementation was PRD-faithful; the fixture failed to re-establish the startup-clock precondition it implicitly assumes. Verified all 25+ callers of `setup_selling_scenario`/`setup_measured_delivery` set the clock only *after* fixture setup, so the reset is safe everywhere.

2. `test_helpers/api_errors.py` — added the missing `ERR_INVOICE_STATE` member to the `ApiErrorId` enum. Root cause of `test_invoice_mark_paid_requires_issued` (in `test_10_corner_state_machines.py`): `AttributeError: type object 'ApiErrorId' has no attribute 'ERR_INVOICE_STATE'`. The rule is verbatim in PRD §3.7 ("Any transition outside this machine fails with `ERR_INVOICE_STATE`") and §2.8 step 7, and the implementation already raises it (HTTP 409 via `err_conflict`). Since PRD §5's catalogue table omits `ERR_INVOICE_STATE` (a doc-generator Zero-Silence gap — the ID exists in §2.8/§3.7 prose but has no §5 row), no HTTP status was registered in `HTTP_STATUS_CODES`; `validate_error` then asserts exactly the PRD-named error_id and nothing more, which is the PRD-faithful assertion strength.

**Fixes applied to `implementation/`: none.** The implementation was PRD-faithful in all three failure modes; both bugs were in the test artifact layer.

**Feedback notes for generators:**
- unit-test-generator: composite fixtures that chain multiple full lifecycle scenarios in one test must re-pin the logical clock between scenarios (clock is global mutable server state; `finalize_episode_measurement` advances it past the forecast horizon).
- doc-generator: `ERR_INVOICE_STATE` is named in §2.8 step 7 and §3.7 prose but missing from the §5 error catalogue table (30 rows vs. 31 named IDs) — a Zero-Silence Rule violation on the HTTP status for that error.
- unit-test-generator: when an error ID is prose-named but not catalogued in §5, the enum member must still be generated in `api_errors.py` (without a status-map entry) so tests can reference it.

**Final state:** 8/8 parallel rounds × 81/81 tests passed under `--isolation per-test-server`.

## Step 8: Finalize PRD — 2026-08-13T12:46:00.000Z

Done. PRD_FINALIZED.md written at `tasks/task_1463_podcast_ad_sales_dynamic_insertion/workspace/PRD_FINALIZED.md` with exactly one inserted line.

**Line counts / delta:** PRD.md 295 lines, PRD_FINALIZED.md 296 lines (+1 line, +0.34%).

**Changes (one total):**
- §5 Error Code Catalogue — insert — added `| ERR_INVOICE_STATE | 409 |` row between `ERR_COPY_STATE` and `ERR_NO_APPROVED_COPY`. The error ID was already named in §2.8 step 7 and §3.7 prose but had no §5 row, leaving its HTTP status unpinned (the doc-generator Zero-Silence gap flagged in step_7_diff item 2) — `implementation/routes/invoices.py:156-160` (raise site), `implementation/errors.py:74-75` (`err_conflict` → 409), constant at `implementation/errors.py:33`.

**Step_7_diff items not resulting in edits:**
- Item 1 (`fixtures.py` clock pinning): pure fixture bug. PRD already pins the startup clock verbatim (§2.4, impl `db.py:36`), the inclusive `[now, now+30d]` forecast-eligibility window and zero-forecast rule (§3.1, impl `services.py:51-62`), and the `ERR_INSUFFICIENT_INVENTORY` activation gate (§3.4 gate 7, §2.8 step 12). The implementation was PRD-faithful; nothing was silent.

**Per-edit pre-edit search log:**
1. Edit: §5 `ERR_INVOICE_STATE` row.
   - (a) Subject: HTTP status mapping for `ERR_INVOICE_STATE`.
   - (b) Paths enumerated: `grep -rn "ERR_INVOICE_STATE" implementation/` returned exactly three hits — `errors.py:33` (constant), `routes/invoices.py:13` (import), `routes/invoices.py:158` (sole raise, guarding ISSUE/DISPUTE/MARK_PAID from disallowed states in `transition_invoice`). Read all of `routes/invoices.py` (189 lines) to confirm no second raise site and that adjacent invoice errors (`ERR_CAMPAIGN_NOT_ENDED`, `ERR_MEASUREMENT_PENDING`, `ERR_MAKE_GOOD_OUTSTANDING`, duplicate-invoice `ERR_INVALID_REQUEST`) already carry §5 rows unaffected by this edit; read `errors.py:74-75` confirming `err_conflict` unconditionally emits 409.
   - (c) Wording adjustment: none — the row asserts only the ID→409 mapping, true at the single raise site; no behavioral prose was added, so no off-site path can be mis-described.
