# Worklog — task_1390_corporate_filing_service_ucc_search_filing

## Step 1: Create Task Directory — 2026-08-13T03:07:00.000Z

Task directory and workspace/ pre-created by pipeline dispatch (treated as DONE per instructions).

## Step 2: Generate Scaffold — 2026-08-13T04:01:00.000Z

All three scaffold artifacts are written, lint-clean, and structurally verified. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1390_corporate_filing_service_ucc_search_filing/`)

- **SCAFFOLD.yaml** (1156 lines) — §1.0–§1.7 only; no `scaffold_difficulty_design`/`scaffold_corner_design` keys
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (831 lines) — single top-level key `scaffold_difficulty_design`
- **SCAFFOLD_CORNER_DESIGN.yaml** (1191 lines) — single top-level key `scaffold_corner_design`

## Scaffold surface counts

| Element | Count |
|---|---|
| Entities | 10 (ClientAccount, JurisdictionProfile, Debtor, SecuredParty, FilingRequest, UCCFiling, LienSearch, SearchResultHit, PerfectionReport, FilingEvent) |
| State machines | 4 entities / 23 transitions (FilingRequest has a correction cycle; UCCFiling has parallel dimensions effectiveness × reflection plus a LAPSED→ACTIVE revival loop) |
| Calculations | 7 (office determination, debtor-name normalization, filing fee, expiration anchoring, lapse sweep, priority position, perfection report) |
| Validations | 11 priority tiers (auth → schema → role → ownership → existence → state/OCC → safety → temporal → constraint → fiscal) |
| Endpoints | 42 |
| Error codes | 39 (all referenced by validations or transitions — verified) |
| Roles | 6 (segregation-of-duties model: ClientManager is entity-backed; FilingReviewer cannot approve own intake) |
| Concurrency rules | 2 true OCC races (`patch-request-stale-version`, `ucc3-create-stale-target`; both 412 via `expected_*_version`) |

## Design instance counts

- **Difficulty design: 21 instances** across all 9 rules (dual_variant 2, combinatorial 3 covering modes a/b/c, non-linear SM 2, transitive cascade 2 at depth 3 with different triggers — termination acceptance vs clock lapse, priority conflict 2 on distinct category pairs state×temporal and safety×fiscal, boundary precision 3 on distinct metrics/endpoints, cross-entity state 3 on distinct pairs, temporal overlap 2 with different interval semantics — half-open perfection-slot vs day-bucket capacity, compensating invariant 2 — fee ledger vs UCC-3 open-count)
- **Corner design: 59 instances** (53 full test recipes + 6 `excluded_because` stubs citing difficulty instances) across all 9 claim-extraction sections

## Harder-than-expert difficulty levers baked in

- Continuation expiration anchored to prior expiration +60 months, not filed_at (evaluation-order trap)
- Continuation window `[expiration−6mo, expiration)` with inclusive-lower/exclusive-upper boundaries, plus late-recorded in-window acceptance reviving a LAPSED filing
- Quoted-vs-charged fee divergence via profile mutation between approve and submit; single-pass round-half-up (10001 × 1.5 → 15002)
- Jurisdiction-conditional debtor-name rule (DL safe harbor vs legal name) driving both submission validation and search-hit classification
- Priority position with chronological + filing_number tie-break; SIMILAR hits excluded even when earlier
- Forward-projection report variant that ignores in-flight continuations, with inclusive horizon boundary
- Lapse boundary: `expiration_at == now` lapses, one second later survives

## Verification

- `scaffold_lint.py`: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5"** (800 calls scanned; 0 violations after fixing `{id}` path-template naming and one negative-test instance name)
- Custom structural pass: instance names unique across both files; all `${var}` placeholders bound by earlier `captures:`; stubs reference existing difficulty instances; all 39 error ids reachable; all grounds resolve to declared §1.1–§1.6 elements; no forbidden race vocabulary anywhere

No sibling task directories were inspected; the design was generated purely from the scenario text and the skill specification.

## Step 3: Copy Shared Files — 2026-08-13T04:02:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1390_corporate_filing_service_ucc_search_filing/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-13T04:20:00.000Z

All checks pass. The PRD is complete and verified.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1390_corporate_filing_service_ucc_search_filing/workspace/PRD.md` — 323 lines.

**Section list:**
- §1 Introduction (3 paragraphs, business-context/pain-point angle)
- §2 Global Specifications & System-Wide Principles: 2.1 Roles/RBAC (headers, 6 roles, identity prose for entity-backed `ClientManager` vs opaque roles), 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`, byte-identical incl. `req_RANDOMALPHANUM123456`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, list filter params), 2.4 Logical Clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`, lapse-sweep side effect, lazy per-filing refresh), 2.5 Common Resource Properties (incl. `common_fields: false` entities: hits/reports/events carry only `id`+`created_at`), 2.6 Path Hierarchy & Reference Resolution (left-to-right 404s), 2.7 Fees/Precision/Fee Ledger (integer cents, single final round-half-up), 2.8 OCC (both rules, `ERR_STALE_VERSION` 412), 2.9 Validation Order of Precedence (all 11 priorities in order), 2.10 Filing Audit Trail (12 `event_type` values)
- §3 Business Logic & Workflows (8 subsections): 3.1 Onboarding (clients/jurisdictions/debtors/secured parties), 3.2 Intake & county-vs-state determination, 3.3 Review/approval/fee quotation, 3.4 Attempt preparation & submission (name-match rule, collateral sufficiency, expedited capacity, fee formula, fiscal gate), 3.5 Acceptance/rejection/correction loop (all 6 kind-specific acceptance branches with equal density), 3.6 Lapse/revival/cancellation cascades, 3.7 Lien searches & search-to-reflect (hit classification, priority position, REFLECTED never downgraded), 3.8 Perfection reporting (both modes fully specified, INITIAL-only exposure)
- §4 Endpoint Definitions (4-column table, all 42 scaffold endpoints present)
- §5 Error Code Catalogue (2-column table, all 39 error IDs present)

**Coverage confirmation (hard contracts):**
- Contract 1 (Field-Name Coverage): entities[].fields 81/81, request_body 34/34, query_params 17/17 — 0 missing. PASS
- Contract 2 (Rule Coverage): validations priority chain 11/11 expressed in §2.9 in order; concurrency rules 2/2 expressed (write endpoint + `expected_request_version`/`expected_target_filing_version` + `ERR_STALE_VERSION`/412, no race framing); state-machine transitions — ClientAccount 2/2, FilingRequest 10/10 (incl. cascade-cancel), UCCFiling 7/7 across both parallel dimensions, LienSearch 3/3; calculations 7/7 (filing_office, debtor_name_match, filing_fee quoted/charged variants with pinned rounding order, expiration 60-month/6-month window with inclusive/exclusive bounds, lapse sweep, priority_position, perfection_report both variants); all 39 error IDs matchable to trigger prose in §2/§3; all endpoint side_effects expressed; structured field content (defaults, initial values, conditionally-required fields) reconstructible; sibling branches (3 amendment scopes, 3 collateral ops, 2 fee variants, 2 report modes) at equal density. PASS
- Contract 3 (§3 Path Purity): 512 backtick tokens scanned, 0 path tokens, 0 bare HTTP-method tokens, 0 method+path tokens. PASS (the `DELETE` enum value of `collateral_change_op` was rewritten in quoted form to avoid colliding with the HTTP-method token ban while preserving the exact string)

Additional verification: §2.2 block is byte-verbatim; no fuzzy/approximating words; no pseudocode operators; all 65 enum/state values and all 6 role names present verbatim. The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` files were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T04:57:00.000Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (9 files):
- `types.py` — 20 status/vocabulary enums + role enum; TypedDicts for 7 primary resources (with `updated_at`/`version`) and 3 immutable records (`SearchResultHit`, `PerfectionReport`, `FilingEvent` — `id`+`created_at` only, per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (38 endpoints)
- `api_errors.py` — 39 `ApiErrorId` members + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions (audit-field assertions for the 3 immutable records) + fee-ledger invariant checker
- `factories.py` — payload factories; `None` override means "omit optional field"
- `constants.py` — thresholds (60-month effectiveness, 6-month window, 30-day refile, 90-day freshness, 1.5x multiplier, per-kind deltas) + canonical CA profile defaults
- `test_users.py` — shared headers for the 5 opaque roles; `make_client_manager_headers(client_id)` for the entity-backed ClientManager
- `fixtures.py` — composite builders: `setup_client_world`, request state progression (`create_in_review_request`/`create_ready_request`), attempt lifecycle (`submit_attempt`/`accept_attempt`/`reject_attempt`), `create_ucc3_request` (reads target version for the OCC guard), search/report helpers
- `__init__.py` — barrel export

**`test_suite/`** (11 files): `conftest.py` + `test_01`…`test_10` grouped by concern (onboarding/envelope/404s, RBAC/SoD, intake, workflow/correction loop, fees/quotation, submission gates, acceptance windows/slots, lapse cascades/reports, searches/verification, OCC/audit/ledgers).

## Test counts
- **Queue A (Difficulty): 42 tests** — all 21 instances × 2
- **Queue B (Corner): 53 tests** — all 53 non-stub instances × 1
- **Total: 95**, collected cleanly by pytest

## Skipped instances
None beyond the 6 declared `excluded_because:` stubs, which are not translated by design; all 6 cross-references verified to resolve to real difficulty instances (`approve_from_draft_intake_rejected`, `debtor_name_misleading_plain`, `quote_snapshot_frozen_at_approval`, `lapse_sweep_on_clock_set`, `discrepancy_then_reflected_dimension_flip`, `open_ucc3_count_decrement_on_fulfill`). No `skip`/`xfail` markers anywhere.

## Recipe adaptations worth flagging (setup-only; asserted values untouched)
Two difficulty recipes' `setup_api_calls` chains are not executable against a PRD-faithful server; I adjusted the setup while preserving every asserted literal:
1. **`report_as_of_now_vs_forward_projection`** — the recipe reuses one debtor for four INITIAL filings whose ACTIVE intervals overlap (violating §3.5's `ERR_OVERLAPPING_ACTIVE_FILING` slot rule), records search results with `through_date` 2021-09-15 while the clock sits at 2021-08-31 (violating the `through_date <= now` rule), and accepts the F4 termination with `filed_at` after "now". Fix: one debtor per filing, plus clock moves to 2021-09-15 and 2022-01-20 at those steps.
2. **`lapse_boundary_equality_lapses_one_second_survives`** — the recipe sets the clock to `00:00:02Z` before the filing flows, which would put `filed_at` before `submitted_at` (`ERR_INVALID_FILED_AT`). Fix: filing A's flow runs at `00:00:00Z`, filing B's at `00:00:01Z`.

## Audit results
- **Tag audit: clean** — 95/95 tests carry exactly one `Design:` line; every tag resolves to a real instance with matching `rule_id`/`section`; no instance undercovered (A ≥2, B ≥1); no stub tagged.
- **PRD citation audit: clean** — all 143 quoted citation spans survive whitespace-normalized literal grep of `PRD.md` (C1); 8 elided/bold-clipped quotes were rewritten to full sentences during the sweep.
- No "scaffold" references in generated code; no skip/xfail markers.

## Step 6: Generate Implementation — 2026-08-13T04:57:00.000Z

Implementation complete and validated. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1390_corporate_filing_service_ucc_search_filing/workspace/implementation/`)

- `start.sh` — foreground launcher; guarded dependency install (`python3 -c "import flask"` check so per-test reboots skip pip), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0
- `app.py` — Flask entry, envelope error handlers (400/404/405/500), request-scoped store lock
- `db.py` — empty-on-boot in-memory store + logical clock starting at exactly `2026-08-01T00:00:00Z`
- `util.py` — UUIDs, ISO-8601 second-precision parse/format, calendar `add_months`, PRD name normalization
- `errors.py` — all 39 catalog error IDs with exact HTTP statuses
- `response.py` — `meta`/`response_type`/`data` envelope, `req_…` ids, list pagination meta (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, clamp 1–100)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, 6-role RBAC, ClientManager ownership, structural validators (with digit-string coercion for OCC fields)
- `services.py` — fee formula (single final ROUND_HALF_UP on subtotal×1.5; kind deltas 0/1000/1500/500), office determination, name-of-record rule, lapse sweep, cancellation/termination cascades, perfection-report computation, serializers
- `routes/` — `admin.py` (clock, clients, jurisdictions), `parties.py` (debtors, secured parties), `requests.py` (intake/approve/cancel/PATCH/attempts), `filings.py` (submit/acceptance/rejection/withdraw/name-check/events), `searches.py`, `reports.py`

## Coverage
- **Endpoints: 42/42** from the scaffold endpoint table
- **State machines: 4** — ClientAccount (ACTIVE↔SUSPENDED, intake-only gate), FilingRequest (7 states incl. correction cycle IN_PROCESS→CORRECTION_REQUIRED→READY, CLIENT_REQUEST/TARGET_LAPSED/TARGET_TERMINATED cancellations), UCCFiling (parallel effectiveness × reflection dimensions, lapse/revival loop, depth-3 termination and lapse cascades), LienSearch (ORDERED→COMPLETED/VERIFIED/DISCREPANCY)
- **Calculations: 7** — office determination, debtor-name match, quoted/charged fee variants, expiration anchoring (continuation extends from stored expiration, never filed_at), lapse sweep, priority position (chronological + filing-number tie-break), dual-mode perfection report
- **OCC: both rules** (`expected_request_version` on PATCH, `expected_target_filing_version` on UCC-3 creation) at 412; validation precedence per PRD §2.9 implemented in order at every handler

## Boot smoke-test results
- Fresh-boot via `bash start.sh`: clean, HTTP-ready in ~1s (verified repeatedly; the harness itself rebooted the server ~95 times via start.sh with zero restart failures)
- Custom 123-check E2E smoke replaying every difficulty/corner design recipe (fee math 23250/15002/11000, quote-vs-charged divergence, lapse boundary equality, continuation window edges, revival, cascades, reports, DL safe harbor, RBAC/ownership/segregation, OCC): **123/123 PASS**
- `prd-bench-local-run --isolation per-test-server` against the generated suite: **90/95 passed** (`/tmp/results_1390.json`)

## The 5 failures are test-suite bugs, not implementation bugs (implementation cannot influence either)
1. **4× `KeyError: 'root'`** in `test_suite/test_07_acceptance_windows_and_slots.py` (tests at lines 143, 164, 194, 216 access `ctx["root"]`, but `_setup_root_with_submitted_continuation()` only sets `ctx["filing"]` via `setup_active_initial_filing`). The API calls in those tests succeeded (continuation accepted, `2036-03-10` anchoring verified in my smoke); the failure is a test-side dict access.
2. **`test_lapse_boundary_equality_lapses_one_second_survives`** builds filing B for debtor "Beta Holdings, LLC" but the helper's default attempt payload carries `debtor_name_on_filing="Acme Manufacturing, Inc."`; PRD §3.4 requires rejecting that submit (ERR_DEBTOR_NAME_SERIOUSLY_MISLEADING), a rule the suite itself asserts in test_06/test_09. The design recipe in `SCAFFOLD_CORNER_DESIGN.yaml` used the correct name — the generated test dropped the override. My smoke covers this scenario with the correct name and passes (equality lapses, +1s survives).

Both need a one-line test-side fix (use `ctx["filing"]`; pass `debtor_name_on_filing="Beta Holdings, LLC"`) — flagged for the test-generation step rather than patched here to avoid colliding with the still-running test subagent.

## Step 7: Test/Fix Iteration — 2026-08-13T05:30:00.000Z

Two 8-round parallel sweeps run.

**Sweep 1 (baseline)**: union of failures across 8 rounds = 7 deterministic + 9 environmental.
- Deterministic (8/8 rounds), both confirmed as test-side bugs against PRD:
  1. 4x `KeyError: 'root'` in test_07 (continuation tests) — local helper `_setup_root_with_submitted_continuation()` never set `ctx["root"]` (test_08's twin helpers do).
  2. test_08 `test_lapse_boundary_equality_lapses_one_second_survives` — filing B's attempt inherited the factory default `debtor_name_on_filing="Acme Manufacturing, Inc."` while its debtor is "Beta Holdings, LLC"; PRD section 3.4 exact-name-match gate correctly rejected the submit (422 ERR_DEBTOR_NAME_SERIOUSLY_MISLEADING in setup).
- Environmental (sporadic, 1-3 rounds): runner "could not be restarted" setup errors (server boot past the 15s poll window under load avg ~26; a second tenant's 8-round sweep for task_1397 ran concurrently) and mid-test `ConnectionResetError`/`RemoteDisconnected` caused by the session-scoped shared `api_client`'s keep-alive pool holding stale connections across per-test server kill+respawn on the same port.

**Fixes applied**:
- test_suite/test_07: helper now sets `ctx["root"] = ctx["filing"]` (matches test_08 pattern).
- test_suite/test_08: second `setup_active_initial_filing` now passes `attempt_overrides={"debtor_name_on_filing": "Beta Holdings, LLC"}` so the setup obeys PRD section 3.4.
- test_helpers/api_client.py: `api_client.session.headers["Connection"] = "close"` — transport-level hardening; eliminates stale pooled-connection resets across per-test restarts. No assertion changed.
- implementation/start.sh: `.deps_installed` sentinel replaces per-boot `python3 -c "import flask"` spawn — shortens every per-test boot under parallel load.

**Sweep 2 (post-fix): 8/8 rounds at 95/95. CLEAN.**

Subagent exit summary (verbatim):

Clean 8-round parallel sweep achieved: **8/8 rounds at 95/95 passed** (760/760 test executions).

## Summary

- **Iterations run:** 2 (baseline sweep → fixes → verification sweep)

- **Tests deleted:** None. Every failing assertion traced to a verbatim PRD sentence with unique derivability; the deterministic failures were test-side construction bugs, not PRD-silent assertions.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1390_corporate_filing_service_ucc_search_filing/test_suite/test_07_acceptance_windows_and_slots.py` — `_setup_root_with_submitted_continuation()` now sets `ctx["root"] = ctx["filing"]` before returning. Four continuation tests (`test_continuation_extends_from_prior_expiration`, `test_continuation_appends_continued_event_and_bumps_root`, `test_continuation_window_open_inclusive`, `test_continuation_one_second_before_window_open_rejected`) read `ctx["root"]`, matching the pattern test_08's local helpers already used. Assertions untouched; PRD §3.5 citations verified verbatim.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1390_corporate_filing_service_ucc_search_filing/test_suite/test_08_lapse_cascades_and_reports.py` — `test_lapse_boundary_equality_lapses_one_second_survives` now passes `attempt_overrides={"debtor_name_on_filing": "Beta Holdings, LLC"}` for filing B. The old setup paired debtor "Beta Holdings, LLC" with the factory default attempt name "Acme Manufacturing, Inc.", so the PRD §3.4 exact-name-match gate (PRD line 176, verified verbatim) correctly rejected the submit with `ERR_DEBTOR_NAME_SERIOUSLY_MISLEADING`. The fixture, not the implementation check, was the bug.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1390_corporate_filing_service_ucc_search_filing/test_helpers/api_client.py` — set `Connection: close` on the shared session-scoped client's headers. Under `per-test-server` isolation the runner kills and respawns the server on the same port before every test; the pooled keep-alive connection from the dead process was sporadically reused by the next test's first request, surfacing as `ConnectionResetError`/`RemoteDisconnected` mid-test (9 instances across rounds 1-8 of the baseline sweep, none reproducible). Transport-level only; no request/response semantics changed.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1390_corporate_filing_service_ucc_search_filing/workspace/implementation/start.sh` — `.deps_installed` sentinel file replaces the per-boot `python3 -c "import flask"` interpreter spawn. With ~760 server boots per sweep and a second tenant's 8-round sweep (task_1397) loading the same host, this shortens every boot and keeps starts inside the runner's 15s readiness window. No application behavior changed; the pip-install fallback is preserved.

- **Environmental note:** the baseline sweep's non-deterministic failures (runner "could not be restarted" setup errors on otherwise-passing tests like `test_segregation_of_duties_same_user_approve`, plus the connection resets above) correlated with a concurrent 8-round sweep from another pipeline on the same host (load avg ~26). After the two harness-robustness fixes above, the verification sweep ran completely clean even at comparable load.

## Step 8: Finalize PRD — 2026-08-13T05:45:00.000Z

Done. `PRD_FINALIZED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1390_corporate_filing_service_ucc_search_filing/workspace/PRD_FINALIZED.md` — it is a **byte-copy of PRD.md**. No edits were needed.

**Line counts / delta:** PRD.md = 323 lines, PRD_FINALIZED.md = 323 lines, 0% delta (diff confirms identical).

**Per-item analysis of `<step_7_diff>` (all four items traced to implementation; none reveal PRD-silence or PRD-mismatch):**

- **test_07 `_setup_root_with_submitted_continuation()` fixture repair** — The added line `ctx["root"] = ctx["filing"]` is a pure test-context dict alias; the four continuation tests read a key the helper never set. Assertions untouched; no implementation behavior involved. The continuation behavior the tests exercise (window boundaries, acceptance, revival) is already pinned in PRD §3.5/§3.6. No PRD edit.
- **test_08 `debtor_name_on_filing` override** — The test was non-compliant with behavior the PRD already pins verbatim. Verified the impl chain: `routes/filings.py:104-114` (submit validation: name-of-record selection, DL-missing error, exact equality of normalized names → `ERR_DEBTOR_NAME_SERIOUSLY_MISLEADING`), `util.py:65-73` (`normalize_name`: uppercase → strip non-[A-Z0-9 space] → collapse spaces → trim), `services.py:100-107` (`name_of_record`: ORGANIZATION→legal_name; INDIVIDUAL+DL_SAFE_HARBOR→drivers_license_name; else legal_name). All match PRD §3.4 (line ~176) word-for-word, including the name-check read endpoint fields (`routes/filings.py:61-75`). The fix brought the test into compliance with the PRD, not the reverse. No PRD edit.
- **test_helpers/api_client.py `Connection: close`** — Transport-level hardening for per-test server restarts (api_client.py:148); no request/response semantics changed. Outside PRD scope. No edit.
- **implementation/start.sh `.deps_installed` sentinel** — Boot-speed optimization only (start.sh:8-13); no application behavior changed. Outside PRD scope. No edit.

**Pre-edit search log:** No edits were committed, so no per-edit searches were triggered. The per-item verification searches above (submission validation chain, normalization helper, name-of-record helper, name-check endpoint, start.sh, api_client.py) confirmed every step_7_diff item is either a pure test-side fixture repair or a behavior-neutral infra change, with the one behavior-relevant item (test_08) already fully pinned by existing PRD prose.

## Step 9: Complete PRD — 2026-08-13T06:00:00.000Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1390_corporate_filing_service_ucc_search_filing/workspace/PRD_COMPLETED.md`.

**Source vs output:** `PRD_FINALIZED.md` (= `PRD.md`, verified identical) 323 lines / 49,405 chars → `PRD_COMPLETED.md` 323 lines / 52,616 chars. Char delta: **+3,211**, all inline edits; no sections added or removed.

**Counts:** 15 ambiguity-pins, 3 mismatch-revisions (18 edited passages total).

**Changes (section — insert/revise — kind — what changed — impl ref):**
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; out-of-range values clamped (`limit` into [1,100], `offset` to ≥0); ordering ties broken by creation order; `total_count` = filtered count before pagination; `has_more` ⟺ offset + page size < total_count — `implementation/middleware.py:153-167`, `implementation/response.py:32-38`
- §2.4 — revise — ambiguity — clock may be set to any instant, forward or backward; no monotonicity constraint (PRD said only "advances") — `implementation/routes/admin.py:31-44`
- §2.4 — insert — ambiguity — lazy single-filing lapse re-check applies to `GET /filings/{id}` and `GET /filings/{id}/name-check` only; lists and event trail read stored state — `implementation/routes/filings.py:52-84`
- §2.5 — revise — **mismatch** — `created_at`/`updated_at` are second-precision (`2026-08-01T00:00:00Z`), not "three fractional digits" (only the meta request timestamp carries millis) — `implementation/util.py:37-49`, all serializers in `implementation/services.py`
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — `implementation/services.py:64-68`
- §2.7 — insert — ambiguity — request-supplied datetimes converted to UTC (naive read as UTC) and truncated to whole seconds; all emitted resource datetimes rendered second-precision — `implementation/util.py:18-34`
- §2.9 step 2 — insert — ambiguity — malformed or non-object JSON body → `ERR_INVALID_REQUEST`; absent body read as `{}` — `implementation/middleware.py:49-67`
- §3.1 — insert — ambiguity — suspend/reinstate from the wrong state → `ERR_REQUEST_INVALID_STATE` (409) — `implementation/routes/admin.py:94-95,110-111`
- §3.1 — revise — **mismatch** — `state_code` "a two-letter code" → uniqueness is the only enforced constraint; no format validation — `implementation/routes/admin.py:126,137-138`
- §3.1 — insert — ambiguity — `PATCH /debtors/{id}` enforces ownership against the debtor's `client_id` (`ERR_CLIENT_OWNERSHIP_MISMATCH`) despite the non-client path; explicit null clears `drivers_license_name`/`jurisdiction_of_formation` — `implementation/routes/parties.py:88-102`
- §3.2 — insert — ambiguity — non-`INITIAL` `target_filing_id` → `ERR_INVALID_REQUEST`; `NEW_UCC1` intake ignores supplied `target_filing_id`/`expected_target_filing_version` and stores target as null — `implementation/routes/requests.py:91-93,120`
- §3.4 — insert — ambiguity — inapplicable fields stored null on attempts: `amendment_scope` null unless `AMENDMENT`, `collateral_change_op` null unless `COLLATERAL` scope — `implementation/routes/requests.py:356-361`
- §3.4 — insert — ambiguity — name-check never errors on missing name of record; returns `match=false`, `normalized_of_record=null` — `implementation/routes/filings.py:65-76`
- §3.5 INITIAL bullet — insert — ambiguity — sixty-month addition clamps day-of-month to month length when shorter — `implementation/util.py:52-58`, `implementation/routes/filings.py:220`
- §3.5 CONTINUATION bullet — insert — ambiguity — same clamping arithmetic for the +60-month extension; single version increment; `REVIVED` event appended before `CONTINUED` — `implementation/routes/filings.py:227-240`
- §3.5 COLLATERAL bullet — insert — ambiguity — DELETE removes only the first occurrence of the substring — `implementation/routes/filings.py:252-253`
- §3.8 — revise — **mismatch** — report universe is the client's `INITIAL` filing attempts only (PRD said "all filing attempts"); UCC-3 attempts never counted in any bucket (tests corroborate: an ACTIVE TERMINATION attempt is excluded from `active_count`) — `implementation/services.py:187-193`
- §5 — insert — ambiguity — framework fallbacks: undeclared path → `ERR_NOT_FOUND` (404), unsupported method → `ERR_METHOD_NOT_ALLOWED` (405), unexpected failure → `ERR_INTERNAL` (500) — `implementation/app.py:26-40`

All other impl behaviors (endpoint table, RBAC, OCC guards, validation precedence, fee formula, state machines, cascades, search classification/priority, event vocabulary, ledger accounting) were already uniquely pinned by the PRD and left untouched.
