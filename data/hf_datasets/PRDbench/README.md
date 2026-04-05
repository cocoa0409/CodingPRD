# PRDbench

## Dataset Summary

PRDbench is a benchmark dataset containing 50 test cases designed to evaluate code agents' development capabilities in real-world environments. Each PRD Bench test case includes a PRD requirement (PRD query) and an acceptance scoring scheme (Criteria). During evaluation, Code Agents are provided with PRD requirements and acceptance scoring schemes, based on which we measure the agents' code development capabilities in real-world scenarios.

- The dataset was released as part of [Automatically Benchmarking LLM Code Agents through Agent-Driven Annotation and Evaluation](https://arxiv.org/abs/2510.24358)

- You can also find the dataset at [PRDbench](https://github.com/AGI-Eval-Official/PRDBench/tree/main)

## Dataset Structure

```
data/
├── aux_data.json         # Auxiliary data index file, recording the paths of auxiliary data files required for each test case
├── 1/                    # Test case 1
│   ├── src/
│   │   ├── PRD.md       # Product Requirement Document
│   │   └── ...          # Auxiliary data files (e.g., training data, template files, etc., as needed by the test case)
│   └── evaluation/       # Evaluation-related files
│       ├── detailed_test_plan.json    # Detailed test plan
│       ├── metric.json                # Evaluation metric definitions
│       └── ...                        # Other test files
├── 2/                    # Test case 2
│   └── ...
├── ...
└── 50/                   # Test case 50
    └── ...
```

## Test Case Description

Each test case directory contains the following:

### 1. Product Requirement Document and Auxiliary Data
- **Location**: `{test_case_number}/src/`
- **Main files**:
  - `PRD.md`: Product Requirement Document containing complete product requirement descriptions, defining the functions the system needs to implement, technical requirements, and acceptance criteria
  - Auxiliary data files: Some test cases may require additional data files (e.g., training data, template files, etc.), and the paths of these files are recorded in the root directory's `aux_data.json`

### 2. Evaluation Framework
- **Location**: `{test_case_number}/evaluation/`
- **Main files**:
  - `detailed_test_plan.json`: Detailed test plan containing test steps and expected results for each functional point
  - `metric.json`: Evaluation metric definitions used to quantitatively assess the quality of system implementation
  - Other test files: May include various test-related files (e.g., input files, expected output files, etc.) as needed by the test case

## Test Case Types

This directory contains 50 test cases covering the following disciplines and domains (numbers in parentheses):

- **Data Processing and Analysis** (9)
- **Automation and Scripting** (5)
- **Game Development** (1)
- **Desktop and GUI Application Development** (4)
- **Data Structures and Algorithms** (3)
- **Artificial Intelligence and Machine Learning** (9)
- **Introduction to Computer Science** (1)
- **Web Security** (1)
- **Matrix Theory** (1)
- **Software Engineering** (1)
- **Information Security** (1)
- **Compiler Principles** (1)
- **Operations Research** (1)
- **Probability Theory and Stochastic Processes** (1)
- **Education and Research** (3)
- **Information Retrieval and Text Mining** (1)
- **Computer Networks and Communications** (3)
- **Internet of Things** (1)

## detailed_test_plan.json Structure Description

The `detailed_test_plan.json` file is a JSON array where each element represents a test point and contains the following fields:

- **metric**: Test point name, usually containing metric number and functional description
- **description**: Test description, detailing test steps (usually including Pre-check, Preparation, Act, Assert, etc.)
- **type**: Test type, common types include:
  - `shell_interaction`: Command-line interaction test
  - `file_comparison`: File comparison test
  - `unit_test`: Unit test
  - Other custom types
- **testcases**: Test case array, each test case contains:
  - `test_command`: Test command (e.g., `python src/main.py`)
  - `test_input`: Test input file path (optional, may be `null`)
- **input_files**: Input file list (optional, may be `null`)
- **expected_output_files**: Expected output file list (optional, may be `null`)
- **expected_output**: Expected output description, explaining the output results the test should produce

## Notes

- Each test case is independent and can be evaluated separately
- Test case numbers range from 1 to 50, covering different functional scenarios and complexity levels

