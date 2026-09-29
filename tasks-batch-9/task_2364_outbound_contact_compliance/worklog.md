# Worklog — task_2364_outbound_contact_compliance

## Step 1: Create task directory — 2026-09-02T04:21:17.628Z

Created `tasks/task_2364_outbound_contact_compliance/` and `tasks/task_2364_outbound_contact_compliance/workspace/` (directory name pre-allocated by caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T05:55:39.460Z

All three scaffold artifacts for task 2364 are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2364_outbound_contact_compliance/`)

- `SCAFFOLD.yaml` — §1.0–§1.7 + preamble. Scenario text stored verbatim (byte-compared against the supplied string). Profile: `compliance_audit` × `temporal_windowing`, layers `rate_threshold_triggers / cascading_side_effects / dual_variant_calculation / optimistic_concurrency`, `role_model: segregation_of_duties`, `consistency_model: immediate`, `api_prefix: /compliance`.
  - **11 entities, 11 state machines, 2 concurrency rules, 18 calculations, 60 validations (priority-ordered), 52 endpoints, 60 error ids, 5 roles.**
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`: **9 rule blocks / 21 instances** (each of §0.5's nine rules has ≥2 differentiated instances; `combinatorial_formula` has 3 covering modes a/b/c).
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`: **9 sections / 128 instances** = 112 full `test_recipe` instances + 16 `excluded_because` stubs. Per section: entities 25, state_machines 21, calculations 15, validations 35, endpoints 13, errors 2, rbac 6, cross_cutting_complexity_layers 9, consistency_model 2.

**Lint verdict (final run, verbatim)**

```
Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     11
  §1.8 instances scanned:     21
  §1.9 instances scanned:     112
  Calls scanned (§1.8+§1.9):  1711

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Extra verifications run beyond the linter**
- All **60** catalog error ids are referenced by at least one design instance (11 not-found ids in `entities`, 10 `*_STATE_INVALID` in `state_machines`, 24 business rules in `validations`, 401/403/ownership/segregation-of-duties in `rbac`, both 412s in `cross_cutting_complexity_layers`).
- All **52** declared endpoints are exercised by at least one actual `call` (not just prose).
- Placeholder closure checked independently across both design files, including `assert:` lines — every `${var}` is bound by an earlier `captures:` (0 violations); every stub's cited `difficulty_instance` exists by name in the difficulty file; names unique across the union of both files.
- No forbidden concurrency vocabulary in any of the three files; `scaffold_*_design` keys appear only as the sole top-level key of their own file.

**One scaffold correction made while auditing §1.5 reachability**: validation priority 86 originally read "the DialerProfile … is APPROVED", which made `ERR_DIALER_PROFILE_LOCKED` (priority 87) unreachable — a LOCKED profile would always fall to 86 first. It now reads "…has been approved at least once, i.e. its status is not DRAFT (a LOCKED profile falls to priority 87 instead, so both errors stay reachable)", matching the error catalog's own condition text ("still DRAFT at launch time"). The corner instance `launch_refused_while_the_profile_is_locked_by_a_sibling_breach` drives the LOCKED path via the abandonment cascade and asserts `error_id != ERR_DIALER_PROFILE_NOT_APPROVED`.

The sibling-task prohibition was respected throughout: nothing under `tasks/` other than this task's own directory was listed, read, or searched.

## Step 3: Copy shared files — 2026-09-02T05:55:58.512Z

Copied `./INSTRUCTION.md` → `tasks/task_2364_outbound_contact_compliance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T06:13:12.000Z

Verbatim subagent summary:

> PRD generated and audited.
>
> **Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2364_outbound_contact_compliance/workspace/PRD.md` — 454 lines.
>
> **Sections**
> - §1 Introduction — outbound contact compliance (TCPA-style consent, DNC scrubbing, recipient-local calling windows, dialer abandonment, revocation propagation), plus the two design commitments (fixed gate ordering, synchronous cascades).
> - §2 Global Specifications, 10 subsections: 2.1 RBAC and segregation of duties; 2.2 API Response Structure (byte-identical to the shared contract); 2.3 Pagination; 2.4 Resource Identity, Audit Stamps and Versioning; 2.5 The Logical Clock; 2.6 Stale-Version Protection; 2.7 Numeric Precision and Rounding Discipline; 2.8 The Compliance Gate Ladder (all 60 validations in scaffold priority order); 2.9 Nested Reads and Path Resolution; 2.10 Cascades and the Two Conserved Quantities.
> - §3 Business Logic, 9 subsections: 3.1 contacts / reassigned-number checks / frequency cap; 3.2 consent capture, superseding, census, basis selector; 3.3 revocation (two state dimensions, ten-business-day deadline, depth-4 cascade); 3.4 DNC lists and scrub execution; 3.5 calling-window policies, holidays, emergencies; 3.6 script and dialer-profile approval tracks plus pacing; 3.7 campaign assembly, certification, suspension/resume/close; 3.8 attempts, dispositions, dual abandonment rates, breach cascade, rolling rate, voids; 3.9 complaints, dual-variant risk scoring, tiering, litigation clusters.
> - §4 Endpoint Definitions — 52 rows, 4 columns.
> - §5 Error Code Catalogue — 60 rows, 2 columns. Document ends here (no audit footer in the file).
>
> **Coverage audit — all three Hard Contracts PASS**
> - **Contract 1 (field-name coverage): PASS.** 134 entity fields + 80 endpoint input identifiers = 149 unique names; 0 missing from backticked prose. Second pass also verified 60/60 error ids, 5/5 role names, 52/52 endpoint paths, 105/105 enum literals and every state-machine state name present.
> - **Contract 2 (rule coverage): PASS.** 47/47 transitions written as explicit `FROM → TO` pairs; all 60 validations reproduced in priority order with their exact `applies_to` endpoint sets; all 18 calculations with constants and rounding order; both OCC rules (`expected_contact_version`, `expected_campaign_version` on both its endpoints); the depth-4 revocation cascade and the abandonment breach chain; sibling-branch symmetry stated for the close, void, profile-approval and reinstatement branch families.
> - **Contract 3 (§3 path purity): PASS.** 0 slash-leading tokens, 0 bare HTTP methods, 0 method+path pairs anywhere in §3.
>
> Two repairs during audit: added explicit arrow notation for 12 transitions that had been described only in prose, and replaced one fuzzy phrase ("arrived around the same time") with the exact 30-day wording. Neither withheld design file was opened, and no sibling task directory was read.

Subagent's own inline note (retained):

Wrote `workspace/PRD.md` (454 lines): §1 Introduction, §2.1–§2.10, §3.1–§3.9, §4 (52-row endpoint table), §5 (60-row error catalogue). §2.2 byte-identical to the shared response-structure contract.

Generated from `SCAFFOLD.yaml` only. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not opened, grepped or referenced, and no sibling task directory was touched.

**Hard Contract audits (all PASS)**
- Contract 1 — field-name coverage: 134 entity fields + 80 endpoint input identifiers = 149 unique names, 0 missing from backticked prose. Also verified: 60/60 error ids, 5/5 role names, 52/52 endpoint paths, 105/105 enum literals, all state names.
- Contract 2 — rule coverage: 47/47 state-machine transitions written as explicit `FROM → TO` pairs (including the four `CLOSED` branches, both profile-approval branches, the five void branches and the policy `ACTIVE → ACTIVE` self-loop); all 60 validations reproduced in §2.8 in scaffold priority order with their exact `applies_to` endpoint sets; all 18 calculations with their constants; both OCC rules; the depth-4 revocation cascade and the abandonment breach chain.
- Contract 3 — §3 path purity: 0 slash-leading tokens, 0 bare HTTP methods, 0 method+path pairs anywhere in §3.

One prose tightening applied during audit: replaced a fuzzy "arrived around the same time" framing of `pattern_cluster_size` with the exact 30-day-neighbourhood wording.

## Step 5: Generate unit tests — 2026-09-02T06:54:24.492319092Z

Verbatim subagent summary:

Generation is complete and audited.

## Files written

**`test_helpers/` (9 files)** — `types.py` (roles, ~36 enum holders, 11 entity TypedDicts), `api_errors.py` (60 error ids + HTTP-status map registered with the framework validators), `constants.py` (all 27 calculation constants plus fixture phone numbers/states/offsets), `api_client.py` (`ApiClient` with one method per each of the 52 endpoints), `test_users.py` (13 identities across the 5 roles, including `make_consumer_headers(contact_id)`), `factories.py` (one payload factory per write endpoint, `None` keys elided so optional inputs stay absent), `assertions.py` (envelope, common-field, millisecond-timestamp, decimal and the two conserved-quantity assertions), `fixtures.py` (`ComplianceWorld` with ~45 builders and a whole-chain `build(stop_after=...)`), `__init__.py` (barrel).

**`test_suite/` (22 files)** — `conftest.py` plus `test_01_…` through `test_21_…`, **176 tests**, 12,060 lines total.

## Test counts per queue

- **Queue A (Difficulty)** — 64 tests covering **21/21** non-stub instances, every one with ≥2 tests.
- **Queue B (Corner)** — 112 tests covering **112/112** non-stub instances, exactly 1:1, no padding. The 16 `excluded_because:` stubs were not translated.

## Instances skipped

**None.** Every non-stub instance in both indices passed the PRD-first two-condition filter. Where a design instance carried a sub-assertion the PRD does not uniquely derive, the sub-assertion was dropped and the instance still translated (not skipped) — notably: no response-body assertion for `POST /_clock/set_current_utc` (the PRD declares none); no `agent_connect_seconds` retention after a void; no `launched_at` anywhere (the field does not exist in the PRD); `provisional_risk_score == 20.50` in one complaint-cluster instance omitted because the yaml's own derivation yields 22.00; cascade-created internal suppression `source` unasserted (PRD-silent). Two design-index instances specified roles that contradict the §4 table (`declare-emergency` `as: ComplianceOfficer`); the PRD was followed.

## Corrections applied to Stage 1

Three independent subagents flagged, and I confirmed verbatim against the PRD, two wrong-role defects in `test_helpers/fixtures.py` — both now fixed:
- `declare_emergency` sent `ComplianceOfficer`; PRD line 233 and the §4 row make it `PlatformAdmin`-only → now `self.admin`.
- `void_attempt` sent `DialerOperator`; PRD line 305 makes voiding a `ComplianceOfficer` correction → now `self.officer`.

Neither change breaks anything: no test calls those two helpers (the agents had routed around them via direct client calls).

## Verification

- `PYTHONPATH=. python -m pytest test_suite --collect-only -q` → **176 tests collected, 0 errors**.
- `pyflakes` clean across `test_helpers/` and `test_suite/`.
- Mandatory audit (`/tmp/audit_2364.py`) → **0 problems**: every test has exactly one `Design:` line as its final docstring line; every tag resolves to a real non-stub instance (no tag points at a stub); every test carries a ≥8-word docstring fragment that is a literal whitespace-normalised substring of `workspace/PRD.md`; the forbidden word "scaffold" appears nowhere in the generated prose.
- No file under `workspace/implementation/` and no sibling task directory was read or written.

## Step 6: Generate implementation — 2026-09-02T07:36:28.673744730Z

Verbatim subagent summary:

The implementation is complete, boots cleanly from a fresh process, and answers requests.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2364_outbound_contact_compliance/workspace/implementation/`

Core (9): `start.sh` (executable, `exec python3 app.py`, installs Flask only when missing), `requirements.txt` (Flask 3.0.3), `app.py` (blueprint registration + envelope error handlers, binds `0.0.0.0:$PORT` default 10000), `util.py` (ISO-8601 3-digit-ms rendering, Decimal helpers, ROUND_HALF_UP / ROUND_FLOOR), `errors.py` (all 60 error IDs → HTTP statuses), `db.py` (in-memory dict store, logical clock epoch `2026-08-01T00:00:00Z`, no seeding of any kind), `response.py` (`meta`/`response_type`/`data` envelope, `req_` + 20 alnum request ids, list pagination meta), `middleware.py` (ladder steps 1–3), `validation.py` (ladder step 4), `calculations.py` (all §2.7/§3 formulas and constants), `derive.py` (derived fields + the depth-4 revocation and depth-3 abandonment cascades), `lookup.py` (family-ordered 404s).

Routes (13 files under `routes/`): admin, contacts, consent, revocations, suppression, scrubjobs, campaigns, dialer, scripts, policies, attempts, complaints.

## Endpoint count

**52** registered rules: 50 under `/compliance/*` plus `POST /_clock/set_current_utc` and `POST /_rnd/records` — matching the scaffold exactly (verified by enumerating `url_map`).

## Verification performed

- `bash start.sh` boots in under 4 s and serves requests; state is empty on every launch (a fresh boot returns `total_count: 0` for every collection).
- End-to-end happy path exercised: clock set → contact import → RND check → script draft/review/approve → consent capture (with `expected_contact_version`) → dialer profile create/approve → policy publish → suppression entry → campaign create → scrub queue/execute (`DRAFT → PENDING_LAUNCH`) → launch with segregation of duties → attempt (window `540–1260`, local time `12:00`, `max_lines_snapshot 6`) → outcome → complaint intake/substantiate → revocation intake/validate/propagate → list endpoints.
- Cascades verified: 2 abandoned answers at 100.00% → campaign `SUSPENDED/ABANDONMENT_BREACH`, profile `LOCKED/ABANDONMENT_BREACH`, sibling campaign `SUSPENDED/PROFILE_LOCKED`; `ERR_RESUME_BLOCKED` until the profile is re-approved *and* the measurement day rolls over, while the sibling resumes immediately; revocation validate → consents `REVOKED`, contact `SUPPRESSED`, INTERNAL scrubs `INVALIDATED`, both campaigns `SUSPENDED/SCRUB_STALE`, attempt budgets credited back.
- Gate ordering and error mapping spot-checked: `ERR_UNAUTHENTICATED` 401, `ERR_FORBIDDEN_ROLE` 403, `ERR_INVALID_REQUEST` 400 (bad E.164, bad date, `limit=0`), `ERR_CONTACT_NOT_FOUND` 404 (chosen over `ERR_CAMPAIGN_NOT_FOUND` when both are unknown), `ERR_DUPLICATE_PHONE_NUMBER`, `ERR_CONTACT_COOLDOWN_ACTIVE`, `ERR_CAMPAIGN_STATE_INVALID` ahead of the safety block.
- All 60 error IDs and their HTTP statuses cross-checked programmatically against PRD §5 — no mismatches, none uncatalogued, none unused. `pyflakes` reports only three unused imports (no defects).

Two judgment calls worth flagging: recording-consent adequacy at attempt time is applied on all channels (per §3.8's wording) rather than VOICE-only (the SCAFFOLD field note), and a `campaign_id` omitted from a complaint intake is treated as null rather than a 422.

## Step 7: Run tests and iterate — 2026-09-02T13:56:40.000Z

**Result: clean. 16/16 rounds at 176/176 passing across two independent 8-round parallel sweeps. Zero changes were required to `test_suite/`, `test_helpers/`, or `implementation/`.**

### Iterations run
2 full 8-round parallel sweeps (16 rounds total, all `setsid nohup`-wrapped and joined with `wait`).

- **Sweep 1** (`workspace/sweep.log`): rounds 1–8 all `passed=176 / total=176`, `failed=0`, `errors=0`; per-round test-phase duration 725–826 s under heavy host load (port registry showed 72 concurrent holders).
- **Sweep 2** (`workspace/sweep2.log`): rounds 1–8 all `passed=176 / total=176`, `failed=0`, `errors=0`; 425–434 s per round on a lighter host (27 holders).

Both sweeps' `results.{1..8}.json` were verified to contain 176 individual test records each (not truncated/stubbed), with fresh mtimes, and no `Terminated` line appeared in either sweep log.

### Root cause of the prior "75/176 through 134/176" sweep
The earlier sweep was a **reaped sweep**, not a broken artifact. The wide round-to-round spread and the total absence of failures once the sweep was run under `setsid nohup` is the signature described in the task brief: backgrounded rounds taking SIGTERM when an unrelated foreground call returned, killing tests mid-request. Supporting evidence that the implementation has no systemic flakiness surface:

- The test client (`test_helpers/api_client.py:444`, module-level `api_client = ApiClient()`) is session-scoped and holds a `requests.Session`, which *would* be a stale-keep-alive hazard across the runner's per-test server restarts — but the implementation serves via Werkzeug's `WSGIRequestHandler`, whose `protocol_version` is `HTTP/1.0`, so every response closes the connection and no pooled socket survives a restart.
- The suite contains **no** concurrency/race tests (`run_race`, `assert_race_outcome`, thread pools are all absent from `test_suite/`), so `app.run(threaded=False)` in `workspace/implementation/app.py` cannot produce race-window flakiness.
- The runner claims a distinct port per round via `~/.cache/prd-bench-local-runner/ports.tsv`, so the 8 concurrent rounds never collide; each round's ~10 min of pre-test latency in sweep 1 was port-registry/boot contention, not test failure.

### Tests deleted
**None.** No test failed in any round, so no PRD-silence or unique-derivability judgement was ever triggered.

### Fixes applied to `test_helpers/`
**None.** Audited `fixtures.py`, `factories.py`, `assertions.py`, `constants.py`, `api_client.py`, and `test_suite/conftest.py` against the PRD as triage groundwork (role-to-resource mapping, `expected_contact_version`/`expected_campaign_version` re-reads, `DEFAULT_CLOCK = 2026-08-03T00:00:00Z` landing at recipient-local 17:00 inside the 480–1260 window, payload shapes with `None` keys elided). Everything traced correctly to PRD prose; no fixture bug found.

### Fixes applied to `implementation/`
**None.** Read `app.py`, `db.py`, `util.py`, `response.py`, `errors.py`, `middleware.py`, `lookup.py`, `validation.py`, `calculations.py`, `derive.py`, and the route blueprints. Storage is in-memory dicts with no seeding and no on-disk persistence, so `start.sh` re-invocation under `per-test-server` isolation genuinely wipes all state; the §5 error→HTTP map, the §2.8 ladder ordering, and the §2.7 rounding discipline all match the PRD as written.

### Orchestrator verification (independent of subagent report)
Re-read all 8 `results.$i.json` directly: each reports `passed=176 total=176 failed=0 errors=0` with 176 test records. mtimes cluster at 2026-09-02T13:53:1x–13:53:20 (not a same-instant mass death). `grep -c Terminated` returns 0 for both sweep logs. Step 7 confirmed complete.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T13:57:10.000Z

Skip condition satisfied. Step 7 exited on its first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. With an empty `<step_7_diff>` there is no Step-7-traceable PRD-silence or PRD-mismatch site for Step 8 to patch, and Step 8's hard scope forbids edits that do not trace to a `<step_7_diff>` item. Spawning the subagent could therefore only produce out-of-scope edits. `PRD_FINALIZED.md` is intentionally absent; Step 9 will start from `PRD.md`.

Orchestrator decision recorded per AUTONOMY directive — no escalation available, and the skip is the behaviour the skill specifies rather than a judgement call.

## Step 9: Complete PRD — 2026-09-02T14:08:30.000Z

Structure is intact — no sections added or removed, same 453 lines.

**Files:** source `workspace/PRD.md` (453 lines, 105,670 chars) → `workspace/PRD_COMPLETED.md` (453 lines, 112,872 chars). Char delta **+7,146**; 26 lines touched by 32 in-paragraph edits. No new sections, headings, or paragraphs.

**Counts:** 28 ambiguity-pins, 4 mismatch-revisions.

### Changes

- §2.2 Standard Error Response Format — insert — ambiguity — unrouted path / disallowed method / unexpected failure all answer `ERR_INVALID_REQUEST` at 404 / 405 / 500 — `app.py:28-44`
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` and negative `offset` are `ERR_INVALID_REQUEST` — `validation.py:213-236`
- §2.3 Pagination — insert — ambiguity — ordering ties (`created_at`, and `received_at`/`requested_at` on the two reverse lookups) settled by insertion order, earliest first — `db.py:89-91`, `contacts.py:112-113`, `scrubjobs.py:166-167`
- §2.3 Pagination — insert — ambiguity — enum filters reject out-of-set values; `litigation_flag` accepts only true/false/1/0; identifier and `state_code` filters match by exact string and return an empty page when unmatched — `validation.py:239-261`, `suppression.py:60-73`
- §2.4 Versioning — **revise** — **mismatch** — PRD claimed "recomputing them counts as a mutation"; impl recomputes on read without touching `updated_at`/`version`, and cascade recomputes bump only when the value actually changes — `derive.py:1-8,173-181,324-329,495-510`
- §2.4 Versioning — insert — ambiguity — client-supplied ISO instants are accepted at any offset and stored normalised to canonical UTC — `validation.py:163-168`, `util.py:61-64`
- §2.5 Logical Clock — insert — ambiguity — clock endpoint answers 200 with `{current_utc}` — `admin.py:25`
- §2.5 Logical Clock — insert — ambiguity — RND seeding answers 201 with `{phone_number, reassigned_on}`, no audit stamps, re-seed overwrites — `admin.py:34-35`
- §2.7 Rounding — insert — ambiguity — percentages travel as JSON numbers, so `0.00` renders as `0.0` — `util.py:93-95`
- §2.8 step 3 — insert — ambiguity — ownership check fires only when the body carries `contact_id`; missing key or unparseable body falls through to step 4; a present-but-unequal value is refused before type-checking — `middleware.py:70-72`
- §2.8 step 4 — insert — ambiguity — empty body reads as `{}`; a non-object JSON body is `ERR_INVALID_REQUEST`; GETs ignore any body — `middleware.py:33-57`
- §3.2 consent selector — insert — ambiguity — residual tie after `captured_at`/`created_at` goes to the earliest-inserted record — `derive.py:79-90`
- §3.3 hop 2 — insert — ambiguity — exact field shape of the server-created internal suppression entry (`INTERNAL`/`CONSUMER_REQUEST`/now/null state) — `derive.py:385-397`
- §3.3 hop 4 — insert — ambiguity — a non-`ACTIVE` campaign of an invalidated job keeps its status but still bumps `version` — `derive.py:440-444`
- §3.3 propagate — **revise** — ambiguity — `target_systems` is a required array of strings that may be empty — `revocations.py:145`
- §3.4 suppression `state_code` — **revise** — **mismatch** — PRD said "ignored" for NATIONAL/INTERNAL; impl validates and stores it (still unused in matching) — `suppression.py:27-30`
- §3.4 `latest_scrub_status` — insert — **mismatch** — documented `created_at` tiebreak is degenerate; impl picks the most recently queued job — `derive.py:52-63`
- §3.4 scrub-history listing — insert — ambiguity — that listing breaks a `requested_at` tie the opposite way, so its head may differ from `latest_scrub_status` — `scrubjobs.py:166-167`
- §3.5 policy publication — insert — ambiguity — `effective_to` ≤ `effective_from` is `ERR_INVALID_REQUEST`, not `ERR_POLICY_PERIOD_OVERLAP` — `policies.py:39-40`
- §3.5 policy selector — insert — ambiguity — residual tie goes to the earliest-inserted policy — `derive.py:93-108`
- §3.6 `covered_state_codes` — insert — ambiguity — duplicates accepted and stored as supplied — `scripts.py:48-50`
- §3.6 `disclosure_blocks` — insert — ambiguity — each block persisted as exactly `block_type` + `text`, extra keys dropped — `scripts.py:33`
- §3.6 pacing — insert — ambiguity — an outcome/void recomputing the same ceiling does not bump the profile — `derive.py:324-329`
- §3.7 `target_state_codes` — insert — ambiguity — duplicates accepted and stored as supplied — `campaigns.py:40-42`
- §3.8 cooldown basis — insert — ambiguity — residual tie goes to the most recently created attempt — `attempts.py:51-56`
- §3.8 `ABANDONED` — insert — ambiguity — a supplied `agent_connect_seconds` is persisted alongside the abandonment — `attempts.py:328-329`
- §3.8 `NO_ANSWER`/`MACHINE_ANSWERED` — insert — ambiguity — supplied `agent_connect_seconds`/`abandon_message_played` accepted but not persisted — `attempts.py:322-329`
- §3.8 breach cascade — insert — ambiguity — a profile not `APPROVED` is left alone and the sibling-suspension hop still runs — `attempts.py:264-273`
- §3.9 adjudicated variant — insert — ambiguity — unattributed complaint yields `verified_attempt_count` 0 and `exposure_cents` 0 — `derive.py:513-521`
- §3.9 clustering — insert — ambiguity — a null `campaign_id` clusters only with other unattributed complaints — `derive.py:478-492`
- §3.9 clustering — insert — ambiguity — dismissed row's own size rewritten excluding itself (may hit 0); only changed rows bump; anchor never double-bumps — `derive.py:495-510`, `complaints.py:73,148,163`

### Orchestrator verification
`workspace/PRD_COMPLETED.md` exists (112,872 bytes), ends with the complete §5 error→HTTP catalogue table (not truncated mid-section), and has an identical `^#` heading count to `PRD.md` — confirming no sections were added or dropped. Pipeline complete.
