import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope, assertJobAssignment,
    createAndActivateGroomingDay,
    createSessionBlock,
    createGroomingJob,
    createGroomerStation,
    createJobAssignment,
    confirmJobAssignment,
    fillSessionBlockWithJobs, markSessionBlockReady, GroomingDay,
    SessionBlock,
    GroomingJob,
    GroomerStation,
    JobAssignment,
    SessionBlockStatus,
    GroomingJobStatus,
    JobAssignmentStatus,
    UserRole,
    RequiredAllergenType,
    SpecialCapabilityName,
    ApiErrorId,
    createUnixTimestamp,
    addMinutes, generatePetId,
    SYSTEM_CONSTANTS
} from '../../../test-helpers';

describe('Phase 6: Mixed Test Cases', () => {
    const managerHeaders = buildUserHeaders('manager-001', UserRole.ClinicManager);
    const techHeaders = buildUserHeaders('tech-001', UserRole.GroomingTechnician);
    const billingHeaders = buildUserHeaders('billing-001', UserRole.BillingAdmin);

    describe('P3-ASSIGN-NEXUS-01.14: Break period violation - job starts too close to existing job', () => {
        it('should reject assignment if new job starts less than 15 minutes after existing job ends', async () => {
            const groomingDay = await createAndActivateGroomingDay('Break Test Day', 1000.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Break Test Block', 8, 8);

            const station = await createGroomerStation(
                groomingDay.id,
                'Test Station',
                'Standard',
                20.0
            );

            const day2At8AM = createUnixTimestamp(32);
            const existingJob = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(1),
                'Existing Grooming',
                32,
                120
            );

            const existingAssignment = await createJobAssignment(
                groomingDay.id,
                existingJob.id,
                station.id
            );
            await confirmJobAssignment(groomingDay.id, existingAssignment.id);

            const newJobStartTime = addMinutes(existingJob.end_time, 14);
            const newJob = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(2),
                'New Grooming',
                (newJobStartTime - Date.now() / 1000) / 3600,
                60
            );

            const res = await apiClient.createJobAssignment(
                groomingDay.id,
                { job_id: newJob.id, station_id: station.id },
                techHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BREAK_PERIOD_VIOLATION });
        });
    });

    describe('TC-E2E-08: Pet allergy conflict created after assignments', () => {
        it('should prevent re-assignment when pet conflict is created after pets are already assigned', async () => {
            const groomingDay = await createAndActivateGroomingDay('Conflict Test Day', 2000.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Conflict Block', 8, 8);

            const station1 = await createGroomerStation(groomingDay.id, 'Station 1', 'Standard', 15.0);
            const station2 = await createGroomerStation(groomingDay.id, 'Station 2', 'Standard', 15.0);

            const pet1Id = generatePetId(101);
            const pet2Id = generatePetId(102);

            const job1 = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                pet1Id,
                'Job A',
                8,
                60
            );

            const job2 = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                pet2Id,
                'Job B',
                9,
                60
            );

            const assignment1 = await createJobAssignment(groomingDay.id, job1.id, station1.id);
            await confirmJobAssignment(groomingDay.id, assignment1.id);

            const assignment2 = await createJobAssignment(groomingDay.id, job2.id, station2.id);
            await confirmJobAssignment(groomingDay.id, assignment2.id);

            const conflictJob = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                pet1Id,
                'Conflict Job',
                10,
                60,
                { cannotBeGroomedWithPetIds: [pet2Id] }
            );

            await apiClient.terminateJobAssignment(groomingDay.id, assignment1.id, managerHeaders);

            const res = await apiClient.createJobAssignment(
                groomingDay.id,
                { job_id: conflictJob.id, station_id: station1.id },
                techHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PET_ALLERGY_CONFLICT });
        });
    });

    describe('P4-READONLY-01.1: GroomingJob duration_minutes readonly field', () => {
        it('should ignore user-provided duration_minutes and calculate from timestamps', async () => {
            const groomingDay = await createAndActivateGroomingDay('Duration Test Day', 1000.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Duration Block', 8, 8);

            const startTime = 1700000000;
            const endTime = 1700018000;

            const jobRes = await apiClient.createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                {
                    pet_id: generatePetId(1),
                    job_type: 'Bath & Brush',
                    start_time: startTime,
                    end_time: endTime,
                    required_allergen_type: RequiredAllergenType.NONE,
                    duration_minutes: 9999,
                } as any,
                techHeaders
            );

            const job = handleApiResponse<GroomingJob>(jobRes, 201);
            expect(job.duration_minutes).toBe(300);
        });
    });

    describe('P3-ASSIGN-NEXUS-01.15: Pet allergy conflict symmetrical check', () => {
        it('should reject assignment if conflicted pet is already assigned in the same block', async () => {
            const groomingDay = await createAndActivateGroomingDay('Symmetrical Test Day', 1500.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Symmetrical Block', 8, 8);

            const station1 = await createGroomerStation(groomingDay.id, 'Station 1', 'Standard', 20.0);
            const station2 = await createGroomerStation(groomingDay.id, 'Station 2', 'Standard', 20.0);

            const pet1Id = generatePetId(201);
            const pet2Id = generatePetId(202);

            const job2 = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                pet2Id,
                'Job B',
                8,
                60
            );

            const assignment2 = await createJobAssignment(groomingDay.id, job2.id, station2.id);

            const job1 = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                pet1Id,
                'Job A',
                9,
                60,
                { cannotBeGroomedWithPetIds: [pet2Id] }
            );

            const res = await apiClient.createJobAssignment(
                groomingDay.id,
                { job_id: job1.id, station_id: station1.id },
                techHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PET_ALLERGY_CONFLICT });
        });
    });

    describe('P3-ASSIGN-CREATE-XX: Break period violation prevents assignment creation', () => {
        it('should reject assignment creation if it violates break period with another CONFIRMED assignment', async () => {
            const groomingDay = await createAndActivateGroomingDay('Break Violation Day', 2000.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Break Block', 8, 12);

            const station = await createGroomerStation(groomingDay.id, 'Test Station', 'Standard', 25.0);

            const job1EndTime = createUnixTimestamp(8 + 10);
            const job1 = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(1),
                'First Job',
                8,
                600
            );

            const job2StartTime = addMinutes(job1EndTime, 10);
            const job2 = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(2),
                'Second Job',
                (job2StartTime - Date.now() / 1000) / 3600,
                120
            );

            const assignment1 = await createJobAssignment(groomingDay.id, job1.id, station.id);
            await confirmJobAssignment(groomingDay.id, assignment1.id);

            const assignmentRes = await apiClient.createJobAssignment(
                groomingDay.id,
                { job_id: job2.id, station_id: station.id },
                techHeaders
            );

            validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_BREAK_PERIOD_VIOLATION });
        });
    });

    describe('P3-CASCADE-CANCEL-01.2: Block cancellation cascades to jobs with no assignments', () => {
        it('should cascade cancellation to jobs even when they have no assignments', async () => {
            const groomingDay = await createAndActivateGroomingDay('Cascade Test Day', 1000.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Cascade Block', 8, 8);

            const job = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(1),
                'Unassigned Job',
                8,
                60
            );

            expect(job.status).toBe(GroomingJobStatus.PENDING);

            await apiClient.updateSessionBlockStatus(
                groomingDay.id,
                sessionBlock.id,
                { status: SessionBlockStatus.CANCELLED },
                managerHeaders
            );

            const jobAfterRes = await apiClient.getGroomingJob(groomingDay.id, sessionBlock.id, job.id, techHeaders);
            const jobAfter = handleApiResponse<GroomingJob>(jobAfterRes, 200);
            expect(jobAfter.status).toBe(GroomingJobStatus.CANCELLED);
        });
    });

    describe('P3-CANCEL-ASSIGN-01.3: Terminate confirmed assignment on PLANNING block', () => {
        it('should revert job to PENDING but not change PLANNING block status', async () => {
            const groomingDay = await createAndActivateGroomingDay('Terminate Test Day', 1500.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Terminate Block', 8, 8);
            const station = await createGroomerStation(groomingDay.id, 'Test Station', 'Standard', 30.0);
            const job = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(1),
                'Test Job',
                8,
                60
            );

            const assignment = await createJobAssignment(groomingDay.id, job.id, station.id);
            await confirmJobAssignment(groomingDay.id, assignment.id);

            const blockBeforeRes = await apiClient.getSessionBlock(groomingDay.id, sessionBlock.id, techHeaders);
            expect(handleApiResponse<SessionBlock>(blockBeforeRes, 200).status).toBe(SessionBlockStatus.PLANNING);

            const terminateRes = await apiClient.terminateJobAssignment(groomingDay.id, assignment.id, managerHeaders);
            const terminatedAssignment = handleApiResponse<JobAssignment>(terminateRes, 200);
            expect(terminatedAssignment.status).toBe(JobAssignmentStatus.TERMINATED);

            const jobAfterRes = await apiClient.getGroomingJob(groomingDay.id, sessionBlock.id, job.id, techHeaders);
            expect(handleApiResponse<GroomingJob>(jobAfterRes, 200).status).toBe(GroomingJobStatus.PENDING);

            const blockAfterRes = await apiClient.getSessionBlock(groomingDay.id, sessionBlock.id, techHeaders);
            expect(handleApiResponse<SessionBlock>(blockAfterRes, 200).status).toBe(SessionBlockStatus.PLANNING);
        });
    });

    describe('P1-BLOCK-02.2: List session blocks for existing day', () => {
        it('should successfully retrieve list of blocks for a day', async () => {
            const groomingDay = await createAndActivateGroomingDay('List Test Day', 1000.0);

            const blockA = await createSessionBlock(groomingDay.id, 'Block A', 8, 4);
            const blockB = await createSessionBlock(groomingDay.id, 'Block B', 13, 4);

            const listRes = await apiClient.getSessionBlocks(groomingDay.id, techHeaders);
            const blocks = handleApiResponse<SessionBlock[]>(listRes, 200, { expectPaginated: true });

            expect(blocks).toHaveLength(2);
            const blockIds = blocks.map(b => b.id);
            expect(blockIds).toContain(blockA.id);
            expect(blockIds).toContain(blockB.id);
        });
    });

    describe('P1-JOB-03.1: List grooming jobs for block', () => {
        it('should retrieve all jobs under a block', async () => {
            const groomingDay = await createAndActivateGroomingDay('Job List Day', 1000.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Job List Block', 8, 8);

            const job1 = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(1),
                'Job 1',
                8,
                60
            );
            const job2 = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(2),
                'Job 2',
                9,
                60
            );

            const listRes = await apiClient.getGroomingJobs(groomingDay.id, sessionBlock.id, techHeaders);
            const jobs = handleApiResponse<GroomingJob[]>(listRes, 200, { expectPaginated: true });

            expect(jobs).toHaveLength(2);
            const jobIds = jobs.map(j => j.id);
            expect(jobIds).toContain(job1.id);
            expect(jobIds).toContain(job2.id);
        });
    });

    describe('P1-ASSIGN-02.2: Get specific job assignment', () => {
        it('should retrieve a specific assignment by ID within its day', async () => {
            const groomingDay = await createAndActivateGroomingDay('Get Assignment Day', 1000.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Get Block', 8, 8);
            const job = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(1),
                'Test Job',
                8,
                60
            );
            const station = await createGroomerStation(groomingDay.id, 'Test Station', 'Standard', 20.0);

            const assignment = await createJobAssignment(groomingDay.id, job.id, station.id);

            const getRes = await apiClient.getJobAssignment(groomingDay.id, assignment.id, techHeaders);
            const retrieved = handleApiResponse<JobAssignment>(getRes, 200);

            assertJobAssignment(retrieved);
            expect(retrieved.id).toBe(assignment.id);
            expect(retrieved.grooming_day_id).toBe(groomingDay.id);
        });
    });

    describe('P1-ASSIGN-06.1: List all job assignments for day', () => {
        it('should list all assignments within a day', async () => {
            const groomingDay = await createAndActivateGroomingDay('Assignment List Day', 2000.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Assignment Block', 8, 8);

            const job1 = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(1),
                'Job 1',
                8,
                60
            );
            const job2 = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(2),
                'Job 2',
                9,
                60
            );

            const station1 = await createGroomerStation(groomingDay.id, 'Station 1', 'Standard', 15.0);
            const station2 = await createGroomerStation(groomingDay.id, 'Station 2', 'Standard', 15.0);

            const assignment1 = await createJobAssignment(groomingDay.id, job1.id, station1.id);
            const assignment2 = await createJobAssignment(groomingDay.id, job2.id, station2.id);

            const listRes = await apiClient.getJobAssignments(groomingDay.id, techHeaders);
            const assignments = handleApiResponse<JobAssignment[]>(listRes, 200, { expectPaginated: true });

            expect(assignments).toHaveLength(2);
            const assignmentIds = assignments.map(a => a.id);
            expect(assignmentIds).toContain(assignment1.id);
            expect(assignmentIds).toContain(assignment2.id);
        });
    });

    describe('P1-STATION-04.1: List all groomer stations for day', () => {
        it('should list all stations within a day', async () => {
            const groomingDay = await createAndActivateGroomingDay('Station List Day', 1000.0);

            const stationA = await createGroomerStation(groomingDay.id, 'Station A', 'Standard', 20.0);
            const stationB = await createGroomerStation(groomingDay.id, 'Station B', 'Premium', 35.0);

            const listRes = await apiClient.getGroomerStations(groomingDay.id, techHeaders);
            const stations = handleApiResponse<GroomerStation[]>(listRes, 200, { expectPaginated: true });

            expect(stations).toHaveLength(2);
            const stationIds = stations.map(s => s.id);
            expect(stationIds).toContain(stationA.id);
            expect(stationIds).toContain(stationB.id);
        });
    });

    describe('P3-CREATE-JOB-01.5: Job duration_minutes derived field', () => {
        it('should automatically populate and accurately calculate duration_minutes', async () => {
            const groomingDay = await createAndActivateGroomingDay('Duration Calc Day', 1000.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Duration Block', 8, 8);

            const jobRes = await apiClient.createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                {
                    pet_id: generatePetId(1),
                    job_type: 'Full Service Grooming',
                    start_time: 1700000000,
                    end_time: 1700010800,
                    required_allergen_type: RequiredAllergenType.NONE,
                },
                techHeaders
            );
            const job = handleApiResponse<GroomingJob>(jobRes, 201);

            expect(job.duration_minutes).toBe(180);
        });
    });

    describe('P2-PAGINATION-01: Pagination on list endpoints', () => {
        it('should respect limit and offset and return correct metadata for the last page', async () => {
            const groomingDay = await createAndActivateGroomingDay('Pagination Day', 2000.0);

            await createGroomerStation(groomingDay.id, 'Station 1', 'Standard', 20.0);
            await createGroomerStation(groomingDay.id, 'Station 2', 'Standard', 20.0);
            const stationC = await createGroomerStation(groomingDay.id, 'Station 3', 'Premium', 35.0);

            const listRes = await apiClient.getGroomerStations(groomingDay.id, techHeaders, { limit: 1, offset: 2 });

            expect(listRes.status).toBe(200);
            expect(listRes.data.meta.limit).toBe(1);
            expect(listRes.data.meta.offset).toBe(2);
            expect(listRes.data.meta.total_count).toBe(3);
            expect(listRes.data.meta.has_more).toBe(false);
            const stations = listRes.data.data as GroomerStation[];
            expect(stations).toHaveLength(1);
            expect(stations[0].id).toBe(stationC.id);
        });

        it('should return has_more: true when more records exist', async () => {
            const groomingDay = await createAndActivateGroomingDay('Pagination More Day', 2000.0);

            await createGroomerStation(groomingDay.id, 'Station A', 'Standard', 20.0);
            await createGroomerStation(groomingDay.id, 'Station B', 'Standard', 20.0);
            await createGroomerStation(groomingDay.id, 'Station C', 'Premium', 35.0);

            const listRes = await apiClient.getGroomerStations(groomingDay.id, techHeaders, { limit: 2, offset: 0 });

            expect(listRes.status).toBe(200);
            expect(listRes.data.meta.has_more).toBe(true);
            expect(listRes.data.data).toHaveLength(2);
        });
    });

    describe('TC-COMPLEX-02: Allergy Score Reconciliation Test', () => {
        it('should correctly reverse allergy score penalty when a peak session assignment is terminated', async () => {
            const groomingDay = await createAndActivateGroomingDay('Allergy Reconciliation Day', 3000.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Reconciliation Block', 8, 12);

            const station = await createGroomerStation(
                groomingDay.id,
                'Recon Station',
                'Standard',
                25.0
            );

            const jobs = await fillSessionBlockWithJobs(
                groomingDay.id,
                sessionBlock.id,
                6,
                8,
                { jobDurationMinutes: 60 }
            );

            for (let i = 0; i < 5; i++) {
                const assignment = await createJobAssignment(groomingDay.id, jobs[i].id, station.id);
                await confirmJobAssignment(groomingDay.id, assignment.id);
            }

            const peakAssignment = await createJobAssignment(groomingDay.id, jobs[5].id, station.id);
            expect(peakAssignment.is_peak_session).toBe(true);

            const dayCheck1Res = await apiClient.getGroomingDay(groomingDay.id, managerHeaders);
            const dayCheck1 = handleApiResponse<GroomingDay>(dayCheck1Res, 200);
            expect(dayCheck1.allergy_exposure_score).toBe(SYSTEM_CONSTANTS.PEAK_SESSION_PENALTY);

            await apiClient.terminateJobAssignment(groomingDay.id, peakAssignment.id, managerHeaders);

            const dayCheck2Res = await apiClient.getGroomingDay(groomingDay.id, managerHeaders);
            const dayCheck2 = handleApiResponse<GroomingDay>(dayCheck2Res, 200);
            expect(dayCheck2.allergy_exposure_score).toBe(0);
        });
    });

    describe('TC-COMPLEX-04: Cascading State Reversion Test', () => {
        it('should automatically revert block from READY_FOR_GROOMING to PLANNING when an assignment is terminated', async () => {
            const groomingDay = await createAndActivateGroomingDay('Cascading Reversion Day', 2000.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Cascading Block', 8, 8);

            const station = await createGroomerStation(
                groomingDay.id,
                'Cascade Station',
                'Standard',
                25.0
            );

            const job = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(1),
                'Cascade Job',
                8,
                480
            );

            const assignment = await createJobAssignment(groomingDay.id, job.id, station.id);
            await confirmJobAssignment(groomingDay.id, assignment.id);

            const readyBlock = await markSessionBlockReady(groomingDay.id, sessionBlock.id);
            expect(readyBlock.status).toBe(SessionBlockStatus.READY_FOR_GROOMING);

            await apiClient.terminateJobAssignment(groomingDay.id, assignment.id, managerHeaders);

            const jobFinalCheckRes = await apiClient.getGroomingJob(groomingDay.id, sessionBlock.id, job.id, techHeaders);
            const jobFinalCheck = handleApiResponse<GroomingJob>(jobFinalCheckRes, 200);
            expect(jobFinalCheck.status).toBe(GroomingJobStatus.PENDING);

            const blockFinalCheckRes = await apiClient.getSessionBlock(groomingDay.id, sessionBlock.id, managerHeaders);
            const blockFinalCheck = handleApiResponse<SessionBlock>(blockFinalCheckRes, 200);
            expect(blockFinalCheck.status).toBe(SessionBlockStatus.PLANNING);
        });
    });

    describe('TC-EXTREME-02: Complex Multi-Block Pet Allergy Conflict', () => {
        it('should block conflicted pets in the same block but allow them in different blocks', async () => {
            const groomingDay = await createAndActivateGroomingDay('Multi-Block Conflict Day', 5000.0);

            const block1 = await createSessionBlock(groomingDay.id, 'Block 1', 8, 8);
            const block2 = await createSessionBlock(groomingDay.id, 'Block 2', 17, 8);

            const station1 = await createGroomerStation(groomingDay.id, 'Station 1', 'Standard', 30.0);
            const station2 = await createGroomerStation(groomingDay.id, 'Station 2', 'Standard', 30.0);

            const pet1Id = generatePetId(301);
            const pet2Id = generatePetId(302);

            const job1Block1 = await createGroomingJob(
                groomingDay.id,
                block1.id,
                pet1Id,
                'Block1 Job1',
                8,
                480
            );

            const job2Block1 = await createGroomingJob(
                groomingDay.id,
                block1.id,
                pet2Id,
                'Block1 Job2',
                10,
                240,
                { cannotBeGroomedWithPetIds: [pet1Id] }
            );

            const job1Block2 = await createGroomingJob(
                groomingDay.id,
                block2.id,
                pet1Id,
                'Block2 Job1',
                17,
                480
            );

            const assignment1 = await createJobAssignment(groomingDay.id, job1Block1.id, station1.id);

            const assignment2Res = await apiClient.createJobAssignment(
                groomingDay.id,
                { job_id: job2Block1.id, station_id: station2.id },
                techHeaders
            );
            validateErrorEnvelope(assignment2Res, {
                expectedErrorId: ApiErrorId.ERR_PET_ALLERGY_CONFLICT,
            });

            const assignment3Data = await createJobAssignment(groomingDay.id, job1Block2.id, station2.id);
            expect(assignment3Data.station_id).toBe(station2.id);
            expect(assignment3Data.status).toBe(JobAssignmentStatus.PROPOSED);
        });
    });

    describe('TC-EXTREME-03: Allergen Type Validation with Multiple Requirements', () => {
        it('should handle complex allergen scenarios with missing and matching capabilities', async () => {
            const groomingDay = await createAndActivateGroomingDay('Allergen Test Day', 3000.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Allergen Block', 8, 12);

            const allergyStation = await createGroomerStation(
                groomingDay.id,
                'Allergy-Safe Station',
                'Hypoallergenic',
                40.0,
                [SpecialCapabilityName.NUT_ALLERGY_SAFE]
            );

            const standardStation = await createGroomerStation(
                groomingDay.id,
                'Standard Station',
                'Standard',
                25.0
            );

            const nutAllergyJob = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(401),
                'Nut Allergy Job',
                8,
                120,
                { requiredAllergenType: RequiredAllergenType.NUT_ALLERGY }
            );

            const assignment1Data = await createJobAssignment(groomingDay.id, nutAllergyJob.id, allergyStation.id);
            expect(assignment1Data.status).toBe(JobAssignmentStatus.PROPOSED);

            const grassAllergyJob = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(402),
                'Grass Allergy Job',
                10,
                120,
                { requiredAllergenType: RequiredAllergenType.GRASS_ALLERGY }
            );

            const assignment2Res = await apiClient.createJobAssignment(
                groomingDay.id,
                { job_id: grassAllergyJob.id, station_id: allergyStation.id },
                techHeaders
            );
            validateErrorEnvelope(assignment2Res, {
                expectedErrorId: ApiErrorId.ERR_CAPABILITY_MISMATCH,
            });

            const noAllergyJob = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(403),
                'No Allergy Job',
                12,
                120,
                { requiredAllergenType: RequiredAllergenType.NONE }
            );

            const assignment3Data = await createJobAssignment(groomingDay.id, noAllergyJob.id, standardStation.id);
            expect(assignment3Data.status).toBe(JobAssignmentStatus.PROPOSED);
        });
    });

    describe('TC-EXTREME-04: Budget Precision at Penny Level', () => {
        it('should handle budget calculations with precise penny-level accuracy', async () => {
            const groomingDay = await createAndActivateGroomingDay('Penny Precision Day', 100.01);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Precision Block', 8, 4);

            const station = await createGroomerStation(
                groomingDay.id,
                'Precise Station',
                'Premium',
                33.33
            );

            const job1 = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(501),
                'Precise Job',
                8,
                180
            );

            const assignment1Data = await createJobAssignment(groomingDay.id, job1.id, station.id);
            expect(assignment1Data.status).toBe(JobAssignmentStatus.PROPOSED);
            expect(assignment1Data.provisional_supply_cost).toBeCloseTo(99.99, 2);

            const job2 = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(502),
                'Tiny Job',
                11.25,
                1
            );

            const assignment2Res = await apiClient.createJobAssignment(
                groomingDay.id,
                { job_id: job2.id, station_id: station.id },
                techHeaders
            );
            validateErrorEnvelope(assignment2Res, {
                expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_SUPPLIES,
            });
        });
    });

    describe('TC-BILLING-02: Fractional Hours Peak Session Calculation', () => {
        it('should correctly calculate peak session for fractional hours crossing 5-job threshold', async () => {
            const groomingDay = await createAndActivateGroomingDay('Fractional Peak Day', 5000.0);
            const sessionBlock = await createSessionBlock(groomingDay.id, 'Fractional Block', 8, 12);

            const station = await createGroomerStation(
                groomingDay.id,
                'Fractional Station',
                'Standard',
                20.0
            );

            const normalJobs = [];
            for (let i = 0; i < 5; i++) {
                const job = await createGroomingJob(
                    groomingDay.id,
                    sessionBlock.id,
                    generatePetId(600 + i),
                    `Normal Job ${i + 1}`,
                    8 + (i * 0.75),
                    30
                );
                normalJobs.push(job);
            }

            const peakJob = await createGroomingJob(
                groomingDay.id,
                sessionBlock.id,
                generatePetId(606),
                'Peak Job',
                8 + (5 * 0.75),
                30
            );

            const normalAssignments: JobAssignment[] = [];
            for (const job of normalJobs) {
                const assignment = await createJobAssignment(groomingDay.id, job.id, station.id);
                normalAssignments.push(assignment);
            }

            const peakAssignmentData = await createJobAssignment(groomingDay.id, peakJob.id, station.id);

            for (const assignment of normalAssignments) {
                await confirmJobAssignment(groomingDay.id, assignment.id);
            }
            await confirmJobAssignment(groomingDay.id, peakAssignmentData.id);

            await apiClient.initiateInvoicing(groomingDay.id, managerHeaders);
            await apiClient.generateInvoiceReport(groomingDay.id, billingHeaders);

            const finalAssignmentsRes = await apiClient.getJobAssignments(groomingDay.id, managerHeaders);
            const finalAssignments = handleApiResponse<JobAssignment[]>(finalAssignmentsRes, 200, { expectPaginated: true });

            const finalPeakAssignment = finalAssignments.find(a => a.id === peakAssignmentData.id);
            const finalNormalAssignment = finalAssignments.find(a => a.id === normalAssignments[0].id);

            expect(finalNormalAssignment?.final_supply_cost).toBeCloseTo(10.0, 2);
            expect(finalPeakAssignment?.final_supply_cost).toBeCloseTo(15.0, 2);
            expect(finalNormalAssignment?.is_peak_session).toBe(false);
            expect(finalPeakAssignment?.is_peak_session).toBe(true);
        });
    });
});
