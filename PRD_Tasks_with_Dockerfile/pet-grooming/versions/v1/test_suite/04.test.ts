import {
    apiClient,
    buildUserHeaders,
    getSuccessData,
    validateErrorEnvelope,
    createAndActivateGroomingDay,
    createSessionBlock,
    createGroomingJob,
    createGroomerStation,
    createJobAssignment,
    confirmJobAssignment, createPeakSessionAssignments,
    markSessionBlockReady,
    addHours,
    addMinutes,
    createUnixTimestamp,
    generatePetId,
    UserRole,
    RequiredAllergenType,
    SpecialCapabilityName,
    GroomingDayStatus,
    SessionBlockStatus,
    GroomingJobStatus,
    JobAssignmentStatus,
    ApiErrorId,
    GroomingDay,
    SessionBlock,
    GroomingJob, JobAssignment, CreateGroomingJobPayload, JobAssignmentPayload
} from '../../../test-helpers';

describe('Phase 3: Pet Grooming Business Logic Unit Tests', () => {
    const managerHeaders = buildUserHeaders('manager-1', UserRole.ClinicManager);
    const techHeaders = buildUserHeaders('tech-1', UserRole.GroomingTechnician);
    const billingHeaders = buildUserHeaders('billing-1', UserRole.BillingAdmin);

    describe('create-job-rule', () => {
        it('Happy path - create job under active day: should successfully create a grooming job with valid data', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);

            const jobPayload: CreateGroomingJobPayload = {
                pet_id: generatePetId(1),
                job_type: 'Full Grooming',
                required_allergen_type: RequiredAllergenType.NONE,
                start_time: createUnixTimestamp(2),
                end_time: createUnixTimestamp(2) + 3600,
            };
            const response = await apiClient.createGroomingJob(day.id, block.id, jobPayload, techHeaders);
            const job = getSuccessData<GroomingJob>(response);

            expect(job.pet_id).toBe(generatePetId(1));
            expect(job.job_type).toBe('Full Grooming');
            expect(job.required_allergen_type).toBe(RequiredAllergenType.NONE);
            expect(job.status).toBe(GroomingJobStatus.PENDING);
            expect(job.duration_minutes).toBe(60);

            const getResponse = await apiClient.getGroomingJob(day.id, block.id, job.id, managerHeaders);
            const retrievedJob = getSuccessData<GroomingJob>(getResponse);
            expect(retrievedJob.id).toBe(job.id);
            expect(retrievedJob.job_type).toBe('Full Grooming');
        });
    });

    describe('create-assignment-nexus-rule', () => {
        it('Happy path - non-peak session assignment: should create assignment with correct state and ledger effects', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 50000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);

            const job = await createGroomingJob(
                day.id,
                block.id,
                generatePetId(1),
                'Basic Grooming',
                2,
                60
            );

            const assignmentPayload: JobAssignmentPayload = {
                job_id: job.id,
                station_id: station.id,
            };
            const response = await apiClient.createJobAssignment(day.id, assignmentPayload, techHeaders);
            const assignment = getSuccessData<JobAssignment>(response);

            expect(assignment.status).toBe(JobAssignmentStatus.PROPOSED);
            expect(assignment.is_peak_session).toBe(false);
            expect(assignment.provisional_supply_cost).toBe(20.00);

            const jobCheckResponse = await apiClient.getGroomingJob(day.id, block.id, job.id, managerHeaders);
            const updatedJob = getSuccessData<GroomingJob>(jobCheckResponse);
            expect(updatedJob.status).toBe(GroomingJobStatus.SCHEDULED);

            const dayCheckResponse = await apiClient.getGroomingDay(day.id, managerHeaders);
            const updatedDay = getSuccessData<GroomingDay>(dayCheckResponse);
            expect(updatedDay.supply_stock_balance).toBe(49980.00);
            expect(updatedDay.allergy_exposure_score).toBe(0);
        });

        it('Peak session assignment - insufficient budget: should reject assignment when provisional cost exceeds budget', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 500.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 100.00);

            await createPeakSessionAssignments(day.id, block.id, station.id, 5, 2);

            const peakJob = await createGroomingJob(
                day.id,
                block.id,
                generatePetId(100),
                'Peak Grooming',
                8,
                60
            );

            const response = await apiClient.createJobAssignment(
                day.id,
                { job_id: peakJob.id, station_id: station.id },
                techHeaders
            );

            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_SUPPLIES });
        });

        it('Day not active: should reject assignment if day is in PLANNING state', async () => {
            const dayResponse = await apiClient.createGroomingDay(
                { schedule_name: 'Planning Day', total_supply_budget: 5000.00 },
                managerHeaders
            );
            const planningDay = getSuccessData<GroomingDay>(dayResponse);

            const activeDay = await createAndActivateGroomingDay('Active Day', 5000.00);
            const block = await createSessionBlock(activeDay.id, 'Test Block', 1, 8);
            const job = await createGroomingJob(activeDay.id, block.id, generatePetId(1), 'Test Job', 2, 60);
            const station = await createGroomerStation(activeDay.id, 'Station 1', 'Standard', 20.00);

            const response = await apiClient.createJobAssignment(
                planningDay.id,
                { job_id: job.id, station_id: station.id },
                techHeaders
            );

            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_DAY_NOT_ACTIVE });
        });

        it('Job belongs to different day: should reject assignment if job belongs to a different day', async () => {
            const dayA = await createAndActivateGroomingDay('Day A', 5000.00);
            const dayB = await createAndActivateGroomingDay('Day B', 5000.00);

            const blockB = await createSessionBlock(dayB.id, 'Block B', 1, 8);
            const jobB = await createGroomingJob(dayB.id, blockB.id, generatePetId(1), 'Job B', 2, 60);

            const stationA = await createGroomerStation(dayA.id, 'Station A', 'Standard', 20.00);

            const response = await apiClient.createJobAssignment(
                dayA.id,
                { job_id: jobB.id, station_id: stationA.id },
                techHeaders
            );

            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_JOB_NOT_FOUND });
        });

        it('Job not PENDING: should reject assignment if job is not in PENDING state', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const job = await createGroomingJob(day.id, block.id, generatePetId(1), 'Test Job', 2, 60);

            const station1 = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);
            const station2 = await createGroomerStation(day.id, 'Station 2', 'Standard', 20.00);

            await apiClient.createJobAssignment(day.id, { job_id: job.id, station_id: station1.id }, techHeaders);

            const response = await apiClient.createJobAssignment(
                day.id,
                { job_id: job.id, station_id: station2.id },
                techHeaders
            );

            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_JOB_NOT_PENDING });
        });

        it('Station belongs to different day: should reject assignment if station belongs to a different day', async () => {
            const dayA = await createAndActivateGroomingDay('Day A', 5000.00);
            const dayB = await createAndActivateGroomingDay('Day B', 5000.00);

            const blockA = await createSessionBlock(dayA.id, 'Block A', 1, 8);
            const jobA = await createGroomingJob(dayA.id, blockA.id, generatePetId(1), 'Job A', 2, 60);

            const stationB = await createGroomerStation(dayB.id, 'Station B', 'Standard', 20.00);

            const response = await apiClient.createJobAssignment(
                dayA.id,
                { job_id: jobA.id, station_id: stationB.id },
                techHeaders
            );

            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_STATION_NOT_FOUND });
        });

        it('Missing required capability: should reject assignment if station lacks required allergy capability', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Standard Station', 'Standard', 20.00);

            const job = await createGroomingJob(
                day.id,
                block.id,
                generatePetId(1),
                'Nut Allergy Grooming',
                2,
                60,
                { requiredAllergenType: RequiredAllergenType.NUT_ALLERGY }
            );

            const response = await apiClient.createJobAssignment(
                day.id,
                { job_id: job.id, station_id: station.id },
                techHeaders
            );

            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_CAPABILITY_MISMATCH });
        });

        it('Positive capability match: should create assignment if station has required capability', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(
                day.id,
                'Allergy Safe Station',
                'Hypoallergenic',
                25.00,
                [SpecialCapabilityName.NUT_ALLERGY_SAFE]
            );

            const job = await createGroomingJob(
                day.id,
                block.id,
                generatePetId(1),
                'Nut Allergy Grooming',
                2,
                60,
                { requiredAllergenType: RequiredAllergenType.NUT_ALLERGY }
            );

            const response = await apiClient.createJobAssignment(
                day.id,
                { job_id: job.id, station_id: station.id },
                techHeaders
            );
            const assignment = getSuccessData<JobAssignment>(response);

            expect(assignment.job_id).toBe(job.id);
            expect(assignment.station_id).toBe(station.id);
        });

        it('Break period violation: should reject assignment if break period is violated', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);

            const job1StartTime = createUnixTimestamp(2);
            const job1 = await createGroomingJob(
                day.id,
                block.id,
                generatePetId(1),
                'Job 1',
                2,
                120
            );
            await createJobAssignment(day.id, job1.id, station.id);

            const job2StartTime = addMinutes(addHours(job1StartTime, 2), 10);
            const job2Response = await apiClient.createGroomingJob(
                day.id,
                block.id,
                {
                    pet_id: generatePetId(2),
                    job_type: 'Job 2',
                    start_time: job2StartTime,
                    end_time: job2StartTime + 3600,
                },
                techHeaders
            );
            const job2 = getSuccessData<GroomingJob>(job2Response);

            const response = await apiClient.createJobAssignment(
                day.id,
                { job_id: job2.id, station_id: station.id },
                techHeaders
            );

            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_BREAK_PERIOD_VIOLATION });
        });

        it('Pet allergy conflict: should reject assignment if pet has allergy conflict with another pet in same block', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);

            const pet1Id = generatePetId(1);
            const pet2Id = generatePetId(2);

            const job1 = await createGroomingJob(day.id, block.id, pet1Id, 'Job 1', 2, 60);
            await createJobAssignment(day.id, job1.id, station.id);

            const job2 = await createGroomingJob(
                day.id,
                block.id,
                pet2Id,
                'Job 2',
                4,
                60,
                { cannotBeGroomedWithPetIds: [pet1Id] }
            );

            const response = await apiClient.createJobAssignment(
                day.id,
                { job_id: job2.id, station_id: station.id },
                techHeaders
            );

            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_PET_ALLERGY_CONFLICT });
        });

        it('Insufficient supplies: should reject assignment if cost exceeds remaining budget', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 100.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Expensive Station', 'Premium', 200.00);

            const job = await createGroomingJob(day.id, block.id, generatePetId(1), 'Expensive Job', 2, 60);

            const response = await apiClient.createJobAssignment(
                day.id,
                { job_id: job.id, station_id: station.id },
                techHeaders
            );

            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_SUPPLIES });
        });

        it('Allergy threshold breached: should reject peak assignment when allergy score would breach threshold without override', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 50000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);

            await createPeakSessionAssignments(day.id, block.id, station.id, 9, 2);

            const dayState = await apiClient.getGroomingDay(day.id, managerHeaders);
            const currentDay = getSuccessData<GroomingDay>(dayState);
            expect(currentDay.allergy_exposure_score).toBe(40);

            const newPeakJob = await createGroomingJob(
                day.id,
                block.id,
                generatePetId(200),
                'Peak Job',
                12,
                60
            );

            const response = await apiClient.createJobAssignment(
                day.id,
                { job_id: newPeakJob.id, station_id: station.id },
                techHeaders
            );

            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_ALLERGY_THRESHOLD_BREACHED });
        });

        it('Override when allergy threshold breached: should allow peak assignment with override and apply both penalties', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 50000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);

            await createPeakSessionAssignments(day.id, block.id, station.id, 9, 2);

            const dayState = await apiClient.getGroomingDay(day.id, managerHeaders);
            const currentDay = getSuccessData<GroomingDay>(dayState);
            expect(currentDay.allergy_exposure_score).toBe(40);

            const newPeakJob = await createGroomingJob(
                day.id,
                block.id,
                generatePetId(200),
                'Override Peak Job',
                12,
                60
            );

            const response = await apiClient.createJobAssignment(
                day.id,
                { job_id: newPeakJob.id, station_id: station.id, override_allergy_check: true },
                techHeaders
            );
            const assignment = getSuccessData<JobAssignment>(response);

            expect(assignment.allergy_override_penalty_applied).toBe(true);

            const dayCheckResponse = await apiClient.getGroomingDay(day.id, managerHeaders);
            const updatedDay = getSuccessData<GroomingDay>(dayCheckResponse);
            expect(updatedDay.allergy_exposure_score).toBe(75);
        });

        it('Projected peak session at proposal: should calculate peak eligibility based on other CONFIRMED assignments', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 50000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);

            await createPeakSessionAssignments(day.id, block.id, station.id, 5, 2);

            const dayState1 = await apiClient.getGroomingDay(day.id, managerHeaders);
            const currentDay1 = getSuccessData<GroomingDay>(dayState1);
            expect(currentDay1.allergy_exposure_score).toBe(0);

            const job6 = await createGroomingJob(day.id, block.id, generatePetId(106), 'Job 6', 8, 60);

            const response = await apiClient.createJobAssignment(
                day.id,
                { job_id: job6.id, station_id: station.id },
                techHeaders
            );
            const assignment = getSuccessData<JobAssignment>(response);

            expect(assignment.is_peak_session).toBe(true);
            expect(assignment.provisional_supply_cost).toBeCloseTo(30.00);

            const dayState2 = await apiClient.getGroomingDay(day.id, managerHeaders);
            const currentDay2 = getSuccessData<GroomingDay>(dayState2);
            expect(currentDay2.allergy_exposure_score).toBe(10);
        });
    });

    describe('confirm-assignment', () => {
        it('Happy path confirmation: should confirm assignment and update job status', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);
            const job = await createGroomingJob(day.id, block.id, generatePetId(1), 'Test Job', 2, 60);
            const assignment = await createJobAssignment(day.id, job.id, station.id);

            const confirmResponse = await apiClient.confirmJobAssignment(day.id, assignment.id, managerHeaders);
            const confirmedAssignment = getSuccessData<JobAssignment>(confirmResponse);

            expect(confirmedAssignment.status).toBe(JobAssignmentStatus.CONFIRMED);

            const jobCheckResponse = await apiClient.getGroomingJob(day.id, block.id, job.id, managerHeaders);
            const confirmedJob = getSuccessData<GroomingJob>(jobCheckResponse);
            expect(confirmedJob.status).toBe(GroomingJobStatus.CONFIRMED);
        });

        it('Cannot confirm non-proposed assignment: should reject confirming assignment not in PROPOSED state', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);
            const job = await createGroomingJob(day.id, block.id, generatePetId(1), 'Test Job', 2, 60);
            const assignment = await createJobAssignment(day.id, job.id, station.id);

            await apiClient.confirmJobAssignment(day.id, assignment.id, managerHeaders);

            const response = await apiClient.confirmJobAssignment(day.id, assignment.id, managerHeaders);

            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED });
        });
    });

    describe('check-block-readiness', () => {
        it('Cannot mark ready with no jobs: should reject marking block ready when it has no jobs', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Empty Block', 1, 8);

            const response = await apiClient.updateSessionBlockStatus(
                day.id,
                block.id,
                { status: SessionBlockStatus.READY_FOR_GROOMING },
                managerHeaders
            );

            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_JOBS_NOT_CONFIRMED });
        });

        it('Cannot mark ready with unconfirmed jobs: should reject marking block ready when jobs are not confirmed', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);
            const job = await createGroomingJob(day.id, block.id, generatePetId(1), 'Unconfirmed Job', 2, 60);
            await createJobAssignment(day.id, job.id, station.id);

            const response = await apiClient.updateSessionBlockStatus(
                day.id,
                block.id,
                { status: SessionBlockStatus.READY_FOR_GROOMING },
                managerHeaders
            );

            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_JOBS_NOT_CONFIRMED });
        });

        it('Can mark ready with all confirmed jobs: should allow marking block ready when all jobs are confirmed', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);
            const job = await createGroomingJob(day.id, block.id, generatePetId(1), 'Confirmed Job', 2, 60);
            const assignment = await createJobAssignment(day.id, job.id, station.id);
            await confirmJobAssignment(day.id, assignment.id);

            const response = await apiClient.updateSessionBlockStatus(
                day.id,
                block.id,
                { status: SessionBlockStatus.READY_FOR_GROOMING },
                managerHeaders
            );
            const readyBlock = getSuccessData<SessionBlock>(response);

            expect(readyBlock.status).toBe(SessionBlockStatus.READY_FOR_GROOMING);
        });
    });

    describe('cascade-block-cancellation', () => {
        it('Cancel block cascades to jobs and assignments: should cancel all jobs/assignments and revert ledgers when block cancelled', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);

            const block1 = await createSessionBlock(day.id, 'Unaffected Block', 1, 4);
            const block2 = await createSessionBlock(day.id, 'Cancelled Block', 5, 4);

            const station = await createGroomerStation(day.id, 'Station A', 'Standard', 50.00);

            const baselineJob = await createGroomingJob(day.id, block1.id, generatePetId(1), 'Baseline Job', 1, 120);
            const baselineAssignment = await createJobAssignment(day.id, baselineJob.id, station.id);
            await confirmJobAssignment(day.id, baselineAssignment.id);
            const baselineCost = 100.00;

            const jobA = await createGroomingJob(day.id, block2.id, generatePetId(2), 'Job A', 5, 60);
            const assignmentA = await createJobAssignment(day.id, jobA.id, station.id);

            const jobB = await createGroomingJob(day.id, block2.id, generatePetId(3), 'Job B', 6.5, 90);
            const assignmentB = await createJobAssignment(day.id, jobB.id, station.id);
            await confirmJobAssignment(day.id, assignmentB.id);

            const initialDayResponse = await apiClient.getGroomingDay(day.id, managerHeaders);
            const initialDay = getSuccessData<GroomingDay>(initialDayResponse);
            expect(initialDay.allergy_exposure_score).toBe(0);
            const expectedProvisionalCosts = baselineCost + assignmentA.provisional_supply_cost + assignmentB.provisional_supply_cost;
            expect(initialDay.supply_stock_balance).toBe(5000.00 - expectedProvisionalCosts);

            const cancelResponse = await apiClient.updateSessionBlockStatus(
                day.id,
                block2.id,
                { status: SessionBlockStatus.CANCELLED },
                managerHeaders
            );
            const cancelledBlock = getSuccessData<SessionBlock>(cancelResponse);

            expect(cancelledBlock.status).toBe(SessionBlockStatus.CANCELLED);

            const jobACheckResponse = await apiClient.getGroomingJob(day.id, block2.id, jobA.id, managerHeaders);
            expect(getSuccessData<GroomingJob>(jobACheckResponse).status).toBe(GroomingJobStatus.CANCELLED);
            const jobBCheckResponse = await apiClient.getGroomingJob(day.id, block2.id, jobB.id, managerHeaders);
            expect(getSuccessData<GroomingJob>(jobBCheckResponse).status).toBe(GroomingJobStatus.CANCELLED);

            const assignmentACheckResponse = await apiClient.getJobAssignment(day.id, assignmentA.id, managerHeaders);
            expect(getSuccessData<JobAssignment>(assignmentACheckResponse).status).toBe(JobAssignmentStatus.TERMINATED);
            const assignmentBCheckResponse = await apiClient.getJobAssignment(day.id, assignmentB.id, managerHeaders);
            expect(getSuccessData<JobAssignment>(assignmentBCheckResponse).status).toBe(JobAssignmentStatus.TERMINATED);

            const baselineCheckResponse = await apiClient.getJobAssignment(day.id, baselineAssignment.id, managerHeaders);
            expect(getSuccessData<JobAssignment>(baselineCheckResponse).status).toBe(JobAssignmentStatus.CONFIRMED);

            const postDayResponse = await apiClient.getGroomingDay(day.id, managerHeaders);
            const postDay = getSuccessData<GroomingDay>(postDayResponse);

            expect(postDay.supply_stock_balance).toBe(5000.00 - baselineCost);
            expect(postDay.allergy_exposure_score).toBe(0);
        });
    });

    describe('terminate-assignment', () => {
        it('should revert job to PENDING and downgrade block to PLANNING when terminating a CONFIRMED assignment in a READY block', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);
            const job = await createGroomingJob(day.id, block.id, generatePetId(1), 'Test Job', 2, 60);

            const assignment = await createJobAssignment(day.id, job.id, station.id);
            await confirmJobAssignment(day.id, assignment.id);

            await markSessionBlockReady(day.id, block.id);

            const terminateResponse = await apiClient.terminateJobAssignment(day.id, assignment.id, managerHeaders);
            const terminatedAssignment = getSuccessData<JobAssignment>(terminateResponse);
            expect(terminatedAssignment.status).toBe(JobAssignmentStatus.TERMINATED);

            const jobCheckResponse = await apiClient.getGroomingJob(day.id, block.id, job.id, managerHeaders);
            const revertedJob = getSuccessData<GroomingJob>(jobCheckResponse);
            expect(revertedJob.status).toBe(GroomingJobStatus.PENDING);

            const blockCheckResponse = await apiClient.getSessionBlock(day.id, block.id, managerHeaders);
            const downgradedBlock = getSuccessData<SessionBlock>(blockCheckResponse);
            expect(downgradedBlock.status).toBe(SessionBlockStatus.PLANNING);
        });

        it('should restore allergy score when terminating an assignment that required an allergy check override', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 50000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);

            await createPeakSessionAssignments(day.id, block.id, station.id, 9, 2);

            const dayMid = await apiClient.getGroomingDay(day.id, managerHeaders);
            const currentDay = getSuccessData<GroomingDay>(dayMid);
            expect(currentDay.allergy_exposure_score).toBe(40);

            const overrideJob = await createGroomingJob(day.id, block.id, generatePetId(200), 'Override Job', 12, 60);
            const overrideAssignment = await createJobAssignment(
                day.id,
                overrideJob.id,
                station.id,
                { overrideAllergyCheck: true }
            );

            const dayBefore = await apiClient.getGroomingDay(day.id, managerHeaders);
            const beforeDay = getSuccessData<GroomingDay>(dayBefore);
            expect(beforeDay.allergy_exposure_score).toBe(75);

            await apiClient.terminateJobAssignment(day.id, overrideAssignment.id, managerHeaders);

            const dayAfter = await apiClient.getGroomingDay(day.id, managerHeaders);
            const afterDay = getSuccessData<GroomingDay>(dayAfter);
            expect(afterDay.allergy_exposure_score).toBe(40);
        });

        it('should revert budget and allergy score when terminating a peak-session assignment', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 50.00);

            await createPeakSessionAssignments(day.id, block.id, station.id, 5, 2);

            const peakJob = await createGroomingJob(day.id, block.id, generatePetId(106), 'Peak Job', 8, 60);
            const peakAssignment = await createJobAssignment(day.id, peakJob.id, station.id);
            await confirmJobAssignment(day.id, peakAssignment.id);

            const dayBeforeTerminate = await apiClient.getGroomingDay(day.id, managerHeaders);
            const beforeDay = getSuccessData<GroomingDay>(dayBeforeTerminate);
            const budgetBeforeTerminate = beforeDay.supply_stock_balance;
            expect(beforeDay.allergy_exposure_score).toBe(10);

            await apiClient.terminateJobAssignment(day.id, peakAssignment.id, managerHeaders);

            const dayAfterTerminate = await apiClient.getGroomingDay(day.id, managerHeaders);
            const afterDay = getSuccessData<GroomingDay>(dayAfterTerminate);
            expect(afterDay.supply_stock_balance).toBeCloseTo(budgetBeforeTerminate + peakAssignment.provisional_supply_cost);
            expect(afterDay.allergy_exposure_score).toBe(0);
        });
    });

    describe('initiate-invoicing', () => {
        it('should allow invoicing initiation when all assignments are resolved', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);

            const job1 = await createGroomingJob(day.id, block.id, generatePetId(1), 'Job 1', 2, 60);
            const assignment1 = await createJobAssignment(day.id, job1.id, station.id);
            await confirmJobAssignment(day.id, assignment1.id);

            const job2 = await createGroomingJob(day.id, block.id, generatePetId(2), 'Job 2', 4, 60);
            const assignment2 = await createJobAssignment(day.id, job2.id, station.id);
            await apiClient.terminateJobAssignment(day.id, assignment2.id, managerHeaders);

            const response = await apiClient.initiateInvoicing(day.id, managerHeaders);
            const invoicingDay = getSuccessData<GroomingDay>(response);
            expect(invoicingDay.status).toBe(GroomingDayStatus.INVOICING_PENDING);
        });

        it('should reject invoicing initiation if day is not ACTIVE', async () => {
            const dayResponse = await apiClient.createGroomingDay(
                { schedule_name: 'Planning Day', total_supply_budget: 5000.00 },
                managerHeaders
            );
            const planningDay = getSuccessData<GroomingDay>(dayResponse);

            const response = await apiClient.initiateInvoicing(planningDay.id, managerHeaders);
            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_DAY_NOT_ACTIVE });
        });
    });

    describe('generate-invoice-report', () => {
        it('should move day to CLOSED and assignment to COMPLETE on successful finalization', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 1000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 100.00);

            const job = await createGroomingJob(day.id, block.id, generatePetId(1), 'Test Job', 2, 60);
            const assignment = await createJobAssignment(day.id, job.id, station.id);
            await confirmJobAssignment(day.id, assignment.id);

            await apiClient.initiateInvoicing(day.id, managerHeaders);
            const finalizeResponse = await apiClient.generateInvoiceReport(day.id, billingHeaders);
            const finalDay = getSuccessData<GroomingDay>(finalizeResponse);

            expect(finalDay.status).toBe(GroomingDayStatus.CLOSED);
            expect(finalDay.supply_stock_balance).toBe(900.00);

            const completedAssignmentResponse = await apiClient.getJobAssignment(day.id, assignment.id, managerHeaders);
            const completedAssignment = getSuccessData<JobAssignment>(completedAssignmentResponse);
            expect(completedAssignment.status).toBe(JobAssignmentStatus.COMPLETE);
            expect(completedAssignment.final_supply_cost).toBe(100.00);
        });

    });

    describe('Extra Tests for Coverage', () => {
        it('should allow assignment if break period is exactly 15 minutes', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 5000.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Station 1', 'Standard', 20.00);

            const job1StartTime = createUnixTimestamp(2);
            const job1EndTime = job1StartTime + 3600;
            const job1 = await createGroomingJob(day.id, block.id, generatePetId(1), 'Job 1', 2, 60);
            const assignment1 = await createJobAssignment(day.id, job1.id, station.id);
            await confirmJobAssignment(day.id, assignment1.id);

            const job2StartTime = addMinutes(job1EndTime, 15);
            const job2Response = await apiClient.createGroomingJob(
                day.id,
                block.id,
                {
                    pet_id: generatePetId(2),
                    job_type: 'Job 2',
                    start_time: job2StartTime,
                    end_time: job2StartTime + 3600,
                },
                techHeaders
            );
            const actualJob2 = getSuccessData<GroomingJob>(job2Response);

            const response = await apiClient.createJobAssignment(
                day.id,
                { job_id: actualJob2.id, station_id: station.id },
                techHeaders
            );
            expect(response.status).toBe(201);
        });

        it('should reject assignment creation with override if budget is insufficient', async () => {
            const day = await createAndActivateGroomingDay('Test Day', 10.00);
            const block = await createSessionBlock(day.id, 'Test Block', 1, 8);
            const station = await createGroomerStation(day.id, 'Expensive Station', 'Premium', 100.00);

            const job = await createGroomingJob(day.id, block.id, generatePetId(1), 'Expensive Job', 2, 60);

            const response = await apiClient.createJobAssignment(
                day.id,
                { job_id: job.id, station_id: station.id, override_allergy_check: true },
                techHeaders
            );
            validateErrorEnvelope(response, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_SUPPLIES });
        });
    });
});
