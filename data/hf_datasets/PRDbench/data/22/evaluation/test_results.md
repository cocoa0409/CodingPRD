# Project Evaluation Report

## Unit Test Results

All unit tests have passed:

- **2.3.1 Alias Method Algorithm Implementation**: Passed
- **2.3.2b Execute Single Round Draw - Weight Application Accuracy**: Passed
- **2.3.3b Execute All Rounds - Duplicate Win Prevention Logic**: Passed

## Functional Test Results

When attempting to run functional tests, the program encountered encoding issues at startup. Due to time constraints, all functional tests could not be completed.

### Issues Identified

1. **Program Startup Failure**:
   - On Windows systems, when attempting to read from files and display text containing special characters (such as ✓ and ✗), the program crashes due to encoding issues.
   - Error message: `UnicodeEncodeError: 'gbk' codec can't encode character '\u2713' in position 0: illegal multibyte sequence`

### Partial Functional Test Results

Below are the completed partial functional test results:

| Test Item | Result | Description |
| :--- | :--- | :--- |
| 0.1 Program Startup and Main Menu | Failed | Program crashes at startup due to encoding issues |
| 2.1.1a Add Participant - User Path Accessibility | Not Tested | Program cannot start |
| 2.1.1b Add Participant - Name and Department Information Handling | Not Tested | Program cannot start |
| 2.1.2a Delete Participant - User Path Accessibility and Double Confirmation | Not Tested | Program cannot start |
| 2.1.3a Modify Participant Weight - User Path Accessibility | Not Tested | Program cannot start |
| 2.1.3b Modify Participant Weight - Weight Value Validation (Lower Limit) | Not Tested | Program cannot start |
| 2.1.3c Modify Participant Weight - Weight Value Validation (Upper Limit) | Not Tested | Program cannot start |
| 2.1.4a Save Participants - User Path Accessibility | Not Tested | Program cannot start |
| 2.2.1a Create Multi-Round Draw - User Path Accessibility | Not Tested | Program cannot start |
| 2.2.1b Create Multi-Round Draw - Round Name and Number Configuration | Not Tested | Program cannot start |
| 2.2.2a Special Weight Configuration - User Path Accessibility | Not Tested | Program cannot start |
| 2.2.3a Preview Draw Rules - User Path Accessibility | Not Tested | Program cannot start |
| 2.2.4a Save Rule Configuration - User Path Accessibility | Not Tested | Program cannot start |
| 2.3.2a Execute Single Round Draw - User Path Accessibility | Not Tested | Program cannot start |
| 2.3.3a Execute All Rounds - User Path Accessibility | Not Tested | Program cannot start |
| 2.4.1a Historical Record Query - User Path Accessibility | Not Tested | Program cannot start |
| 2.4.1b Historical Record Query - Query by Round Name | Not Tested | Program cannot start |
| 2.4.1c Historical Record Query - Query by Participant Name | Not Tested | Program cannot start |
| 2.4.1d Historical Record Query - Query by Date Range | Not Tested | Program cannot start |
| 2.5.1a Input Validation - Numeric Range Validation | Not Tested | Program cannot start |
| 2.5.2a Double Confirmation - Delete Round Operation | Not Tested | Program cannot start |

## Summary

The unit tests for the project's core algorithm (Alias Method) and key business logic (weight application, duplicate win prevention) have all passed, indicating that these implementations are correct.

However, the program has serious encoding compatibility issues on Windows systems, preventing normal startup and functional testing. This issue needs to be addressed as a priority to ensure the program runs properly in different environments.