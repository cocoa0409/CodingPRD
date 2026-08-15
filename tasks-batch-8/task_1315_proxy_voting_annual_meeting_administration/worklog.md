# Worklog — task_1315_proxy_voting_annual_meeting_administration

## Step 1: Create Task Directory — 2026-08-12T21:37:00.000Z

Task directory `tasks/task_1315_proxy_voting_annual_meeting_administration/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline; Step 1 treated as DONE per orchestration instructions.

## Step 2: Generate Scaffold — 2026-08-12T22:24:00.000Z

Scaffold generation complete. All three artifacts are in place and pass the mechanical linter plus my own consistency audit.

## Deliverables (all under /home/ubuntu/github/CodingPRD/tasks/task_1315_proxy_voting_annual_meeting_administration/)

- **SCAFFOLD.yaml** — §1.0–§1.7 (no `scaffold_difficulty_design`/`scaffold_corner_design` keys). Verbatim scenario, domain `proxy-voting-annual-meeting`, flat topology under `/proxy`.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 18 instances, exactly 2 per each of the 9 difficulty rules.
- **SCAFFOLD_CORNER_DESIGN.yaml** — 59 instances (54 active + 5 `excluded_because` stubs) across all 9 claim-extraction sections.

## Design summary

- **Complexity profile**: compliance/audit primary + event-sourcing secondary; layers = optimistic concurrency, dual-variant calculation, scheduled actions, derived-field reconciliation; flat topology; cyclic state-machine shape; segregation-of-duties role model; immediate consistency.
- **Surface**: 11 entities, 54 endpoints (flat collections with per-entity single-GET + filtered-list GETs so every FK is reverse-reachable per lint check (f)), 40 error codes, 3 calculations, 5 roles (Shareholder is `entity_backed:ShareholderAccount`; the rest opaque).
- **Key mechanics**: provisional-vs-final quorum (basis-point rounding, contested-meeting 0.50 floor, walk-in shares at conclude); unofficial-vs-certified weighted tabulation with pinned per-instruction-then-sum rounding (PREFERRED class weight 0.5 → 501+501=1002 vs 1001 trap); latest-valid-vote-wins supersession; revoke; challenge-adjudication cascade (vote → tabulation → quorum → certification supersession, including SIGNED-cert compensation reverting the meeting to MEETING_HELD and proposals to ACTIVE); householding package consolidation with opt-out; half-open session overlap vs 24h-buffer solicitation windows; OCC on Meeting.version for PATCH and certification sign; segregation of duties (signer ≠ certification creator); deterministic logical clock defaulting to 2026-08-01T00:00:00Z via `POST /proxy/_clock/set_current_utc`.

## Verification

- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (54 endpoints, 11 entities, 18 §1.8 + 59 §1.9 instances, 580 calls scanned.)
- Additional scripted audits all pass: every `${var}` placeholder is bound by an earlier `captures:` in the same instance; instance names unique across both design files; every `grounds:` ref resolves to a declared §1.1–§1.7 element; every error code is referenced by a validation/transition; both OCC rules have their `expected_meeting_version` input and version-bump side effect; no forbidden concurrency vocabulary; every `excluded_because` stub cites an existing §1.8 instance and carries no `test_recipe`.
- Fixes applied during the pass: quoted `?`-suffixed optional input markers and bracketed `grounds:` items for YAML validity, quoted array-index capture JSONPaths, renamed the distribution list filter to `covered_account_ids?` to satisfy FK reverse-reachability, removed an undeclared `email` field from a PATCH payload, and widened challenge creation to allow RESULTS_CERTIFIED so the signed-certification compensation cascade is reachable.

## Step 3: Copy Shared Files — 2026-08-12T22:25:55.119Z

Copied `./INSTRUCTION.md` to `tasks/task_1315_proxy_voting_annual_meeting_administration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T22:34:49.516Z

Generated `/home/ubuntu/github/CodingPRD/tasks/task_1315_proxy_voting_annual_meeting_administration/workspace/PRD.md` from the scaffold (I did not open either forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`).

**Document structure:**
- §1 Introduction (2 paragraphs: business context + role/variant framing)
- §2 Global Specs, 11 subsections: RBAC with per-role identity translation (Shareholder is `entity_backed:ShareholderAccount`; the other four are opaque), verbatim §2.2 envelope block, pagination (limit 10/1/100, offset 0, `created_at` ascending), the logical clock (startup default exactly `2026-08-01T00:00:00Z`, never wall clock), common resource properties, a 10-step validation precedence order, OCC rules for the two guarded writes, dual-variant tally principle (PROVISIONAL/FINAL, UNOFFICIAL/CERTIFIED), share-class weighting and basis-point rounding-half-up, and collection filter parameters
- §3 Business Logic in 8 subsections organized along the meeting lifecycle (setup → record-date list & broker search → householding/distribution → proposals & vote capture & tabulation → virtual platform & questions → solicitation campaigns → convene/quorum/conclude → challenges/certification/8-K), with all three calculations (quorum, weighted tabulation with pinned per-instruction-round-then-sum, householding grouping) rendered as reconstructible prose
- §4 endpoint table: 54 rows, 4 columns each; §5 error catalogue: 42 rows, 2 columns

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoints input/query/path identifiers: 63 required, 63 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: 10 categories expressed as explicit ordered list (§2.6), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write op + expected_meeting_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all 28 transitions across 10 machines expressed (from/to states, preconditions with error ids, side effects incl. certification-supersession compensation cascade), 0 missing
- calculations[]: 3 checked, 3 fully expressed (quorum PROVISIONAL/FINAL incl. CONTESTED 0.50 floor and 10000-basis-point scaling; tabulation class weights 1.0/0.5 with per-instruction round-before-sum; householding grouping/representative/order rules), 0 missing
- validations[] conditions: all matchable to error ids in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (lock snapshot, generation/regeneration supersession, vote supersede/revoke/invalidate recompute cascades, challenge UPHELD cascade, sign effects, file-8k stamps), 0 missing
- entities[].fields[] structured content: defaults (NOTICE_AND_ACCESS, false, FOR, shares_held, 0, DRAFT/PENDING/REQUESTED/ACTIVE/VALIDATED/SCHEDULED/SUBMITTED/OPEN) and null-until fields (filed_at, filing_reference, shares_reported, ruling, resolution_note, moderation_note) all stated, 0 missing
- sibling-branch symmetry: DELIVERED/BOUNCED, APPROVE/REJECT/RETURN, UPHELD/OVERRULED, PROVISIONAL/FINAL, UNOFFICIAL/CERTIFIED all rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 415
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All role names, 30+ state/enum values, 42 error IDs (each mentioned in §2/§3 prose), and all 54 endpoint paths verified present programmatically.

## Step 5: Generate Unit Tests — 2026-08-12T23:06:26.292Z

Generation complete. Both final passes are clean.

## What was generated

**`test_helpers/`** (9 files) at `/home/ubuntu/github/CodingPRD/tasks/task_1315_proxy_voting_annual_meeting_administration/test_helpers/`:
- `types.py` — all 11 entity TypedDicts (all carry `common_fields: true`) + 20 status/enum classes
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (46 methods, incl. `variant` query param on the two computed reads and the `_clock/set_current_utc` test-driving endpoint)
- `api_errors.py` — all 42 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions plus `assert_quorum_read`/`assert_tabulation_read`
- `factories.py`, `constants.py` (BP_SCALE 10000, contested floor 0.50, class weights, 24h campaign buffer, clock default `2026-08-01T00:00:00Z`)
- `test_users.py` — opaque role constants + mandatory `make_shareholder_headers(account_id)` entity-backed builder + `make_inspector_headers` for the SoD creator/signer split
- `fixtures.py` — the full lifecycle chain: `create_draft_meeting` → `add_account` → `lock_record_date` → `add_proposal` → `generate_distributions` → `open_voting` → `cast_vote` (threads minted `control_number` + shareholder identity) → `convene_meeting` (advances logical clock) → `conclude_meeting` → `create_certification_draft`/`sign_certification` (fresh OCC version read) → `setup_certified_meeting`/`setup_filed_meeting`

**`test_suite/`** — 12 files, **94 tests**, collecting cleanly under pytest.

## Coverage audit results
- **Queue A (difficulty): all 18 instances × ≥2 tests** — every instance has exactly 2 tests (36 difficulty-tagged tests).
- **Queue B (corner): 58 of 59 non-stub instances** have exactly 1 test. All 7 `excluded_because:` stubs untranslated; every stub's `difficulty_instance` cross-reference verified to resolve.
- Every test's docstring ends with exactly one verbatim `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, all resolving to real instances; no untagged/dual-tagged tests; no `skip`/`skipif`/`xfail`; no scaffold references in comments.
- **PRD citation pass: 152 quoted strings across 94 docstrings, all survive literal normalized search of PRD.md** (fixed 18 initial failures: §2.6 list items need their `**Label.**` markdown, no ellipses, no line-broken hyphenations, trailing periods dropped where PRD clauses end with `;`).

## Two adjudication decisions to be aware of

1. **Skipped instance (gap left as a gap):** `Corner/validations/vote_referencing_other_meeting_proposal_returns_cross_meeting_reference`. The recipe's foreign proposal (`p_other`) sits in a meeting that is only in DRAFT, so two rules fail simultaneously: proposal-not-ACTIVE (PRD §2.6 priority 4, "state") and cross-meeting reference (priority 7). PRD §2.6's explicit precedence ordering points to `ERR_PROPOSAL_NOT_ACTIVE`, while the instance asserts `ERR_CROSS_MEETING_REFERENCE` — two PRD-only readers would ship different outcomes. No test emitted.

2. **Assertion adjustment (instance still covered):** `meeting_creation_applies_defaults_and_system_fields` asserts `version == 1` at creation, but the PRD never pins the initial version value (§2.5/§3.1 say only "increments with every modification" / "increments by one"). I emitted the test asserting all uniquely-derivable claims (status DRAFT, walk_in_shares 0, filed_at/filing_reference null, created_at == logical-clock default via parse-compare) and dropped only the initial-version literal. The same principle applies in `meeting_patch_occ_success_then_stale_rejection`, which asserts `version == observed + 1` rather than the literal 2.

## Step 6: Generate Implementation — 2026-08-12T23:10:00.000Z

Implementation complete. **94/94 tests pass, twice in a row, under `prd-bench-local-run --isolation per-test-server`** (results.1.json and results.2.json).

## What was built

Python + Flask (waitress) implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1315_proxy_voting_annual_meeting_administration/workspace/implementation/`:

- **`start.sh`** — guarded install (`python3 -c "import flask, waitress"` no-op check), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- **`app.py`** — blueprint registration, envelope-shaped 404/405/500 handlers
- **`db.py`** — empty-at-boot in-memory stores (no seeding); logical clock defaulting to exactly `2026-08-01T00:00:00Z` (canonicalized to 3-fractional-digit UTC) which drives *all* timestamps (`created_at`/`updated_at`/`filed_at`, convene check, and envelope `api_request_timestamp`) per PRD §2.4; internal `_seq` counter as creation-order tie-break since the frozen logical clock gives identical `created_at` values
- **`middleware.py`** — `X-User-ID`/`X-User-Role` auth: missing headers *or* undeclared role → 401 `ERR_UNAUTHENTICATED`; role-not-permitted → 403
- **`routes/`** — 12 modules covering all 54 endpoints: meetings CRUD + 10 lifecycle actions + quorum, accounts (12-digit control-number minting), broker searches, material-distribution generate/regenerate, proposals + tabulation, votes, sessions, questions, challenges, campaigns, certifications, and the test clock
- **`services/`** — `quorum.py` (PROVISIONAL/FINAL variants, basis-point round-half-up, CONTESTED 0.50 floor, walk-in handling), `tabulation.py` (pinned per-instruction round-then-sum, 1.0/0.5 class weights, three vote standards, UNOFFICIAL/CERTIFIED), `householding.py` (grouping by `(address_key, delivery_preference)`, earliest-created representative, creation-ordered package emission)

Key fidelity decisions, all traceable to PRD prose:
- Validation precedence §2.6 implemented per-endpoint (auth → role/ownership/channel-matrix → existence → state → segregation → temporal → cross-meeting → domain → OCC → body shape), including subtle orderings like state-before-cross-meeting on vote/challenge create, and segregation (403) before unresolved-challenges (422) before OCC (412) on certification sign
- `UPHELD` adjudication cascade: vote → INVALIDATED, non-superseded DRAFT/SIGNED certifications → SUPERSEDED, and a superseded SIGNED cert reverts the meeting RESULTS_CERTIFIED → MEETING_HELD with PASSED/FAILED proposals back to ACTIVE; `OVERRULED` leaves everything untouched
- Conclude is atomic: FINAL quorum evaluated with the candidate `walk_in_shares`; on failure nothing is persisted
- Half-open session overlap (adjacency allowed) vs. 24-hour either-direction campaign gap; campaign `end_at` must be ≤ `meeting_datetime`

One environment note: this host runs ~10 concurrent pipeline workers that also spawn `python3 app.py` servers — during development I accidentally killed other workers' servers once with a broad `pkill -f "python3 app.py"`; subsequent runs used exact-PID kills only. The two verified green runs (107.6s and ~110s each) confirm no flakiness from the guarded `start.sh`.

## Step 7: Run Tests and Iterate — 2026-08-13T00:11:59.960Z

Both files are in final shape. The exit criterion — a clean 8-round parallel sweep — has been met twice consecutively (sweeps 7 and 8: 94/94 × 8 each, with the shared runner verified byte-identical to its pre-session state).

## Summary

- **Iterations run**: 8 full 8-round sweeps (plus 1 single-round diagnostic). Final two sweeps clean: **all 8 rounds passed 94/94** in each. The final sweep's results are in `/home/ubuntu/github/CodingPRD/tasks/task_1315_proxy_voting_annual_meeting_administration/workspace/implementation/results.{1..8}.json`.

- **Tests deleted**: none. Every failure observed was a `pytest_runtest_setup` infrastructure error ("API server ... could not be restarted") — the tests never executed, so there was no assertion to audit against PRD. The affected tests (e.g., `test_record_date_not_before_meeting_returns_record_date_invalid`, `test_duplicate_account_number_within_meeting_returns_conflict`) trace verbatim to PRD §3.1/§3.2 and passed whenever the server booted; no PRD-silence or unique-derivability issues found.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `implementation/`** (both address the harness kill→respawn race; no endpoints, fields, or behaviors added):
  1. `start.sh` — replaced the per-boot `python3 -c "import flask, waitress"` dependency check (a full interpreter spawn per restart, ~95 restarts per round × 8 rounds) with a one-time sentinel (`/tmp/.task_1315_deps_ok`); added per-port stderr logging for post-hoc crash diagnosis. Boot latency halved (0.75s → 0.37s), and round wall time dropped from ~128s to ~67s.
  2. `app.py` — wrapped `waitress.serve()` in a `_serve_with_bind_retry()` loop: on `EADDRINUSE` it retries with backoff for up to ~10s, then re-raises. **Root cause evidence**: under per-test-server isolation the runner SIGKILLs the previous server and respawns within milliseconds; on a loaded host the killed process's LISTEN socket teardown lags, so the fresh server's bind fails with `EADDRINUSE` and (pre-fix) the process died instantly, exhausting the runner's 15s poll window. I reproduced this directly — rapid kill+respawn cycles produced the exact `OSError: [Errno 98]` traceback from `waitress/wasyncore.py` — and confirmed the fix recovers (transient 3s port squatter → server up at 3.05s; 720-cycle race test: zero failures after fix).

- **Environment note**: sweeps run on a shared host with ~10 other pipeline workers. Dirty sweeps (1, 2, 5, 6) correlated exactly with neighbor-load storms (load avg 12–28, port-registry holders rising mid-sweep); all quiet-period sweeps were clean, including two consecutive clean sweeps at the end. The temporary diagnostic instrumentation I added to the shared runner (`prd-bench-local-runner/.../pytest_plugin.py`) was fully reverted and verified byte-identical to the original.

Orchestrator verification: all 8 final `results.{1..8}.json` report 94/94 passed.

## Step 8: Finalize PRD — 2026-08-13T00:14:11.484Z

**Conclusion: No PRD edit is warranted.** `PRD_FINALIZED.md` is a verbatim copy of `PRD.md`. Both Step 7 fixes are process/boot infrastructure with zero API-visible behavior, and the PRD neither specifies nor should specify process-boot internals.

### PRD.md vs PRD_FINALIZED.md
- Both 318 lines; 0% delta; identical md5 (`e550d93c72518821f798b32fb494d38e`).

### Changes made
- None. Zero inserts, zero revisions.

### Verification searches (the mandatory pre-edit search, applied to the only candidate edit subjects)

**Candidate subject 1 — `start.sh` sentinel dependency check + per-port stderr logging** (`workspace/implementation/start.sh:11-22`):
- (a) Subject: dependency-install gating via `/tmp/.task_1315_deps_ok` sentinel; stderr redirection to `/tmp/.task_1315_server_${PORT}.log`.
- (b) Paths enumerated: read `start.sh` in full; grepped `PRD.md` for `waitress|flask|start.sh|boot|startup|dependenc|pip|install|sentinel|/tmp|stderr|logging|bind|retry|backoff|port|PORT|0.0.0.0|process|signal|socket|server` — the only hits are API-domain prose (`server-generated api_request_id`, `server-minted` UUIDs, the logical-clock startup sentence, broker-search "process"); zero references to boot mechanics. Read `INSTRUCTION.md` — start.sh behavior (PORT/0.0.0.0/foreground/`exec`) is governed by that build contract, not the PRD, and `start.sh` still satisfies it (foreground `exec python3 app.py`, PORT honored).
- (c) N/A — no edit committed; PRD silence here is correct-by-design (boot internals are INSTRUCTION.md's domain), so adding prose would invent constraints the PRD intentionally leaves to the build contract.

**Candidate subject 2 — waitress `EADDRINUSE` bind-retry loop** (`workspace/implementation/app.py:71-97`):
- (a) Subject: `_serve_with_bind_retry()` — up to ~10s backoff retry on `EADDRINUSE` around `waitress.serve(host="0.0.0.0", port=port)`.
- (b) Paths enumerated: read `app.py` in full (retry is confined to the `__main__` block; no route/middleware imports it); grepped all `*.py` for `waitress|EADDRINUSE|sentinel|_serve_with_bind_retry` — hits only in `app.py`; listed `routes/` (12 blueprints) and `services/` (4 modules) and confirmed none touch serve/boot logic; grepped for the one PRD startup-coupled behavior (`2026-08-01`) — logical clock initializes in `db.py:39` (`_CLOCK_DEFAULT`) at module import, entirely upstream of and unaffected by the bind-retry wrapper, so the PRD §2.4 sentence "At server startup the logical clock is set to exactly `2026-08-01T00:00:00Z`" remains exactly true with the fix in place.
- (c) N/A — no edit committed; the PRD's sole startup clause (clock init) is behaviorally unchanged by the retry loop, and no other PRD sentence touches serving, binding, or process lifecycle.

### Supporting evidence from Step 7 diff
- No tests deleted, no `test_helpers/` or `test_suite/` fixes — so there are no weakened assertions or fixture repairs implying PRD ambiguity to pin down.
- Final two 8-round sweeps passed 94/94, confirming the current implementation (with both boot fixes) is the stable alignment target and exhibits no behavior the PRD fails to determine.

`workspace/PRD_FINALIZED.md` is in place as a byte-identical copy of `PRD.md`.

## Step 9: Complete PRD — 2026-08-13T00:25:00.000Z

Done. `workspace/PRD_COMPLETED.md` written.

**Source vs output:** `PRD_FINALIZED.md` (identical to `PRD.md`) — 318 lines / 45,419 chars → `PRD_COMPLETED.md` — 320 lines / 48,881 chars (char-delta +3,462; +2 lines from the one appended paragraph in §2.2).

**Counts:** 21 ambiguity-pins, 2 mismatch-revisions (23 edits total; one edit bundles two related pins).

Changes:

- §2.1 — insert — ambiguity — empty-valued `X-User-ID`/`X-User-Role` headers treated as missing → 401 — implementation/middleware.py:28
- §2.1 — insert — ambiguity — ownership checks on path-identified resources fire after the 404 load; body-supplied `account_id` ownership (vote/question create) fires before existence — implementation/routes/accounts.py:126-128, routes/votes.py:69-72, routes/questions.py:54-56
- §2.2 — insert — ambiguity — fallback errors `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) in the same envelope — implementation/app.py:47-57
- §2.3 — insert — ambiguity — equal-`created_at` ties ordered by server creation sequence (`_seq`) — implementation/util.py:204-207, db.py:83-95
- §2.3 — insert — ambiguity — filters are exact-equality except `covered_account_ids`, which is list-membership — implementation/routes/distributions.py:92-94
- §2.4 — insert — ambiguity — `to_iso8601` must parse, is normalized to UTC with three fractional digits, and may move the clock backward — implementation/db.py:42-64, routes/clock.py:17-22
- §2.5 — insert — ambiguity — `version` starts at 1 at creation — implementation/db.py:92
- §2.6 (item 3) — insert — ambiguity — body-carried identifiers are existence-checked with the same resource-specific not-found codes — implementation/routes/votes.py:75-86
- §2.6 (item 10) — insert — ambiguity — required strings must be non-empty; unrecognized body fields ignored; a field's intrinsic shape is validated within the rule step that consumes it (e.g. `shares_voted` integer shape with the share-range rule, `walk_in_shares` shape before the quorum gate) — implementation/util.py:85-89, routes/votes.py:109-111, routes/meetings.py:303-305
- §2.8 — insert — ambiguity — unrecognized `variant` value → `ERR_INVALID_REQUEST` — implementation/routes/meetings.py:356-357, routes/proposals.py:141-142
- §3.1 — insert — ambiguity — `record_date` read as midnight 00:00:00Z for the ordering comparison; datetime inputs stored/echoed verbatim as supplied — implementation/routes/meetings.py:57-66, 113
- §3.2 — insert — ambiguity — `control_number` is a 12-digit number with non-zero leading digit — implementation/routes/accounts.py:54-56
- §3.2 — insert — ambiguity — `shares_reported` must be a non-negative integer — implementation/routes/broker_searches.py:101-107
- §3.3 — insert — ambiguity — `covered_account_ids` lists members in ascending creation order — implementation/services/householding.py:44-48, 64
- §3.3 — insert — ambiguity — generation responds 201 with a list envelope covering the full new package set (`offset` 0, `limit`/`total_count` = package count) — implementation/routes/distributions.py:81-83
- §3.3 — insert — ambiguity — recorded `delivery_outcome` becomes the package's `status` (no separate field) — implementation/routes/distributions.py:116
- §3.3 — **revise** — **mismatch** — preference updates are also rejected on `CANCELLED` meetings, not only from `MEETING_HELD` onward — implementation/routes/accounts.py:44, 139-143
- §3.4 — insert — ambiguity — `proposal_number` must be an integer — implementation/routes/proposals.py:62-64
- §3.4 — insert — ambiguity — undeclared `channel`/`choice` values → `ERR_INVALID_REQUEST` (shape); `ERR_FORBIDDEN`/`ERR_CHOICE_NOT_ALLOWED` apply only to declared values; non-integer `shares_voted` → `ERR_INVALID_REQUEST`; the instruction echoes the supplied `control_number` (null when absent) — implementation/routes/votes.py:67, 110-135, 154
- §3.5 — insert — ambiguity — session booking is not gated on meeting lifecycle state — implementation/routes/sessions.py:49-54
- §3.6 — insert — ambiguity — campaign booking is not gated on meeting lifecycle state — implementation/routes/campaigns.py:53-56
- §3.7 — **revise** — **mismatch** — conclude validates `walk_in_shares` shape (non-negative integer, `ERR_INVALID_REQUEST`) before the `FINAL` quorum gate, and stores the figure only on success — implementation/routes/meetings.py:303-313
- §3.8 — insert — ambiguity — multiple `OPEN` challenges may target the same instruction; adjudication moves the challenge's `status` to the ruling value; `UPHELD` invalidates the instruction only if still `VALIDATED` while the certification-supersession cascade runs regardless — implementation/routes/challenges.py:78-123, 152-164
- §3.8 — insert — ambiguity — certification `outcomes` map covers each `ACTIVE` proposal only — implementation/routes/certifications.py:57-66

Notable areas verified as already uniquely pinned (no change): vote-channel/role matrix, latest-valid-vote-wins supersession, quorum basis-point math with the 0.50 contested floor, per-instruction half-up rounding before summation, all three vote-standard outcome formulas, householding grouping/representative rules, half-open session windows with 24-hour campaign gaps, OCC endpoints and ordering, and the full UPHELD compensation cascade.
